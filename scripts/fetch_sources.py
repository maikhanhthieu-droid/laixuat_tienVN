"""fetch_sources.py — Fetch 12 PDFs (3 sources × 4 weeks) + upstream.

3 PDF sources:
  - SBV: sbv.gov.vn bulletin (PDF embed, UUID must be scraped from article)
  - VBMA: vbma.org.vn weekly report (direct download, %20 in URL, spacing varies)
  - VNBA: vnba.org.vn article → CDN PDF (md5/expires token present but unenforced)

Upstream sources (portable, no local API):
  - FRED (JSON, needs FRED_API_KEY env) — US 10Y/2Y, DXY
  - vnstock (Python lib) — VN-Index weekly

Usage:
  python3 fetch_sources.py --week 2026-W26 --out ./sources_cache
  python3 fetch_sources.py --week 2026-W26 --out ./sources_cache --upstream-only
"""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
PDF_MAGIC = b"%PDF-"
SBV_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://sbv.gov.vn/vi/th%C3%B4ng-tin-v%E1%BB%81-ho%E1%BA%A1t-%C4%91%E1%BB%99ng-ng%C3%A2n-h%C3%A0ng-trong-tu%E1%BA%A7n",
}

_session_opener = None


def get_session_opener() -> urllib.request.OpenerDirector:
    global _session_opener
    if _session_opener is None:
        import http.cookiejar
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        cj = http.cookiejar.CookieJar()
        _session_opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ctx),
            urllib.request.HTTPCookieProcessor(cj),
        )
    return _session_opener


@dataclass
class WeekRange:
    """ISO week + Mon-Fri dates."""
    iso_week: str  # "2026-W26"
    monday: date
    friday: date

    @property
    def sbv_slug(self) -> str:
        """SBV article URL slug: '01-05.6.2026' or '31.8-04.9.2026'.
        
        Zero-padded day-of-month, unpadded month, full year.
        If week crosses month boundaries, includes both months.
        """
        if (self.monday.year, self.monday.month) != (self.friday.year, self.friday.month):
            return f"{self.monday.day:02d}.{self.monday.month}-{self.friday.day:02d}.{self.friday.month}.{self.friday.year}"
        return f"{self.monday.day:02d}-{self.friday.day:02d}.{self.monday.month}.{self.monday.year}"

    @property
    def vbma_filename(self) -> str:
        """VBMA filename date part: '22062026-26062026' (zero-padded)."""
        return f"{self.monday.strftime('%d%m%Y')}-{self.friday.strftime('%d%m%Y')}"


def enumerate_4_weeks(target_iso_week: str) -> list[WeekRange]:
    """Return [N-3, N-2, N-1, N] as WeekRange objects.

    Handles year roll (W01 ← previous year's last week).
    """
    year_str, week_str = target_iso_week.split("-W")
    year, week = int(year_str), int(week_str)
    weeks = []
    for w in range(week - 3, week + 1):
        if w < 1:
            prev_year = year - 1
            # ISO last week of prev year (52 or 53)
            try:
                last_week = date(prev_year, 12, 28).isocalendar()[1]
            except ValueError:
                last_week = 52
            w_use, y_use = last_week + w, prev_year
        else:
            w_use, y_use = w, year
        monday = date.fromisocalendar(y_use, w_use, 1)
        friday = date.fromisocalendar(y_use, w_use, 5)
        weeks.append(WeekRange(f"{y_use}-W{w_use:02d}", monday, friday))
    return weeks


def curl(url: str, headers: Optional[dict] = None, sleep_s: float = 0.0) -> bytes:
    """HTTP GET returning bytes, with session cookies and optional sleep."""
    hdrs = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    opener = get_session_opener()
    with opener.open(req, timeout=30) as resp:
        data = resp.read()
    if sleep_s:
        time.sleep(sleep_s)
    return data


def download_pdf(
    url: str,
    headers: Optional[dict] = None,
    *,
    retries: int = 3,
    retry_delay_s: float = 1.5,
) -> bytes:
    """Download a PDF and reject WAF/error HTML masquerading as a PDF."""
    last_error: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            data = curl(url, headers=headers)
            if data.startswith(PDF_MAGIC):
                return data
            preview = data[:120].decode("utf-8", errors="replace").replace("\n", " ")
            raise ValueError(
                f"response is not a PDF (bytes={len(data)}, preview={preview!r})"
            )
        except Exception as exc:
            last_error = exc
            if attempt + 1 < max(1, retries):
                time.sleep(retry_delay_s * (attempt + 1))
    raise RuntimeError(
        f"PDF download failed after {max(1, retries)} attempts: {last_error}"
    ) from last_error


def pdftotext(pdf_path: Path, txt_path: Path) -> None:
    """Convert PDF to text via system pdftotext -layout."""
    subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), str(txt_path)],
        check=True, capture_output=True,
    )


def sbv_pdf_filename_candidates(week: WeekRange) -> list[str]:
    """Return likely SBV document-library filenames for a reporting week."""
    labels = [week.sbv_slug]
    if (week.monday.year, week.monday.month) != (week.friday.year, week.friday.month):
        labels.insert(
            0,
            (
                f"{week.monday.day:02d}.{week.monday.month}-"
                f"{week.friday.day:02d}.{week.friday.month}.{week.friday.year}"
            ),
        )
        labels.append(
            f"{week.monday.day:02d}-{week.friday.day:02d}.{week.friday.month}.{week.friday.year}"
        )
    return list(dict.fromkeys(f"{label}.pdf" for label in labels))


def sbv_article_slug_candidates(week: WeekRange) -> list[str]:
    """Return all date slug variations SBV might use for the weekly article."""
    base_prefix = "diễn-biến-thị-trường-ngoại-tệ-và-thị-trường-liên-ngân-hàng-tuần-từ-"
    date_patterns = [week.sbv_slug]
    if (week.monday.year, week.monday.month) != (week.friday.year, week.friday.month):
        date_patterns.extend([
            f"{week.monday.day:02d}.{week.monday.month}-{week.friday.day:02d}.{week.friday.month}.{week.friday.year}",
            f"{week.monday.day:02d}.{week.monday.month:02d}-{week.friday.day:02d}.{week.friday.month:02d}.{week.friday.year}",
            f"{week.monday.day:02d}-{week.friday.day:02d}.{week.friday.month}.{week.friday.year}",
            f"{week.monday.day:02d}-{week.friday.day:02d}.{week.monday.month}.{week.monday.year}",
        ])
    else:
        date_patterns.extend([
            f"{week.monday.day}-{week.friday.day}.{week.monday.month}.{week.monday.year}",
            f"{week.monday.day:02d}-{week.friday.day:02d}.{week.monday.month:02d}.{week.monday.year}",
        ])
    return [f"{base_prefix}{p}" for p in dict.fromkeys(date_patterns)]


def fetch_sbv_week(week: WeekRange, out_dir: Path) -> Optional[Path]:
    """Fetch SBV weekly bulletin PDF → .txt. Returns None if week skipped (holiday).

    The article slug is 'diễn-biến-...-tuần-từ-{D1}-{D2}.{M}.{Y}' (Vietnamese
    with diacritics). We URL-encode the full slug. SBV accepts both /vi/w/ and
    /vi/web/sbv_portal/w/ forms.
    """
    pdf_path = out_dir / f"sbv_{week.iso_week}.pdf"
    txt_path = out_dir / f"sbv_{week.iso_week}.txt"
    pdf_headers = {
        **SBV_HEADERS,
        "Accept": "application/pdf,*/*",
    }

    # 1. Try stable direct URL without UUID (single attempt, no long retry loop if 404/WAF)
    pdf_data = None
    direct_errors = []
    for filename in sbv_pdf_filename_candidates(week):
        for domain in ["https://www.sbv.gov.vn", "https://sbv.gov.vn"]:
            direct_url = f"{domain}/documents/20117/0/" + quote(filename)
            try:
                pdf_data = download_pdf(
                    direct_url,
                    headers={**pdf_headers, "Referer": f"{domain}/vi/trang-chu"},
                    retries=1,
                    retry_delay_s=0.5,
                )
                break
            except Exception as exc:
                direct_errors.append(f"{filename}: {exc}")
        if pdf_data is not None:
            break

    # 2. If direct URL didn't return a PDF, discover the article and its PDF with UUID
    article_errors = []
    article_found = False
    if pdf_data is None:
        article_urls = []

        # 2a. Try listing page discovery
        for list_url in [
            "https://sbv.gov.vn/vi/th%C3%B4ng-tin-v%E1%BB%81-ho%E1%BA%A1t-%C4%91%E1%BB%99ng-ng%C3%A2n-h%C3%A0ng-trong-tu%E1%BA%A7n",
            "https://www.sbv.gov.vn/vi/th%C3%B4ng-tin-v%E1%BB%81-ho%E1%BA%A1t-%C4%91%E1%BB%99ng-ng%C3%A2n-h%C3%A0ng-trong-tu%E1%BA%A7n",
        ]:
            try:
                list_html = curl(list_url, headers=SBV_HEADERS, sleep_s=0.5).decode("utf-8", errors="ignore")
                for m in re.finditer(r'href="([^"]*(?:di%E1%BB%85n-bi%E1%BA%BFn|diễn-biến)[^"]*)"', list_html, re.I):
                    href = m.group(1)
                    if not href.startswith("http"):
                        href = "https://sbv.gov.vn" + href
                    if href not in article_urls:
                        article_urls.append(href)
            except Exception as exc:
                article_errors.append(f"listing: {exc}")

        # 2b. Add candidate slugs across known domains
        for slug in sbv_article_slug_candidates(week):
            for domain in ["https://sbv.gov.vn", "https://www.sbv.gov.vn"]:
                u1 = f"{domain}/vi/w/" + quote(slug)
                u2 = f"{domain}/vi/web/sbv_portal/w/" + quote(slug)
                if u1 not in article_urls:
                    article_urls.append(u1)
                if u2 not in article_urls:
                    article_urls.append(u2)

        for article_url in article_urls:
            try:
                html = curl(article_url, headers=SBV_HEADERS, sleep_s=1.0).decode(
                    "utf-8", errors="ignore"
                )
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    continue
                article_errors.append(f"{article_url}: HTTP {exc.code}")
                continue
            except Exception as exc:
                article_errors.append(f"{article_url}: {exc}")
                continue

            article_found = True
            pdf_match = re.search(
                r'(?:src|href)="(/documents/20117/0/[^"]+\.pdf/[^"]+)"',
                html,
            )
            if not pdf_match:
                preview = html[:120].replace("\n", " ")
                article_errors.append(
                    f"{article_url}: no PDF link (bytes={len(html)}, preview={preview!r})"
                )
                continue

            base_dom = "https://sbv.gov.vn" if "sbv.gov.vn" in article_url else "https://www.sbv.gov.vn"
            pdf_url = base_dom + pdf_match.group(1)
            try:
                pdf_data = download_pdf(
                    pdf_url,
                    headers={**pdf_headers, "Referer": article_url},
                    retries=3,
                    retry_delay_s=2.0,
                )
                break
            except Exception as exc:
                article_errors.append(f"{pdf_url}: {exc}")

    if pdf_data is None:
        if not article_found and not article_errors:
            return None
        details = "; ".join((direct_errors + article_errors)[-4:])
        raise RuntimeError(f"SBV PDF unavailable for {week.iso_week}: {details}")

    pdf_path.write_bytes(pdf_data)
    pdftotext(pdf_path, txt_path)
    return txt_path


def fetch_vbma_by_weeks(out_dir: Path, target_weeks: list) -> dict:
    """Fetch VBMA PDFs for specific ISO weeks by scanning listing pages."""
    from datetime import date as _date
    import time as _time

    results = {}
    remaining = list(target_weeks)

    # Check cache first
    for tw in list(remaining):
        w_short = tw.split("-")[-1]
        cached = out_dir / f"vbma_{w_short}.txt"
        if cached.exists():
            results[w_short] = cached
            remaining.remove(tw)

    if not remaining:
        print(f"  VBMA: all {len(target_weeks)} weeks cached")
        return results

    print(f"  VBMA: fetching {len(remaining)}: {[tw.split('-')[-1] for tw in remaining]}")

    # Scan listing pages to collect PDF hrefs
    all_hrefs = []
    for page in range(1, 6):
        try:
            html = curl(f"https://vbma.org.vn/vi/reports/weekly?page={page}").decode("utf-8", errors="ignore")
            hrefs = re.findall(r'href="(/storage/reports/[^"]+\.pdf)"', html)
            all_hrefs.extend(hrefs)
            if len(hrefs) < 12:
                break
            _time.sleep(0.5)
        except Exception:
            break

    # Download + match by date
    for href in all_hrefs:
        if not remaining:
            break
        pdf_url = "https://vbma.org.vn" + href.replace(" ", "%20")
        tmp_pdf = out_dir / f"vbma_tmp_{len(results)}.pdf"
        tmp_txt = out_dir / f"vbma_tmp_{len(results)}.txt"
        try:
            tmp_pdf.write_bytes(download_pdf(pdf_url))
            pdftotext(tmp_pdf, tmp_txt)
            text = tmp_txt.read_text(encoding="utf-8", errors="ignore")
            dates_found = re.findall(r"(\d{1,2})/(\d{1,2})/(\d{4})", text[:3000])
            matched = False
            for d_str, m_str, y_str in dates_found[:5]:
                try:
                    d_val = _date(int(y_str), int(m_str), int(d_str))
                    iso = d_val.isocalendar()
                    tw_key = f"{iso[0]}-W{iso[1]:02d}"
                    if tw_key in remaining:
                        w_short = tw_key.split("-")[-1]
                        final_txt = out_dir / f"vbma_{w_short}.txt"
                        final_pdf = out_dir / f"vbma_{w_short}.pdf"
                        tmp_txt.rename(final_txt)
                        tmp_pdf.rename(final_pdf)
                        results[w_short] = final_txt
                        remaining.remove(tw_key)
                        print(f"    {w_short}: matched ({d_val})")
                        matched = True
                        break
                except ValueError:
                    continue
            if not matched:
                tmp_pdf.unlink(missing_ok=True)
                tmp_txt.unlink(missing_ok=True)
        except Exception:
            tmp_pdf.unlink(missing_ok=True)
            tmp_txt.unlink(missing_ok=True)

    if remaining:
        print(f"  ⚠️ VBMA not found: {[tw.split('-')[-1] for tw in remaining]}")
    return results


def fetch_vnba_by_weeks(out_dir: Path, target_weeks: list) -> dict:
    """Fetch VNBA PDFs for specific ISO weeks via sidebar chain crawling.

    Strategy: start from known recent article → follow sidebar links backward.
    Handle 429 rate limit with sleep + retry.
    """
    import ssl as _ssl
    import time as _time
    from datetime import date as _date

    ctx = _ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = _ssl.CERT_NONE

    results = {}
    remaining = list(target_weeks)

    # Check cache first
    for tw in list(remaining):
        w_short = tw.split("-")[-1]
        cached = out_dir / f"vnba_{w_short}.txt"
        if cached.exists():
            results[w_short] = cached
            remaining.remove(tw)

    if not remaining:
        print(f"  VNBA: all {len(target_weeks)} weeks cached")
        return results

    print(f"  VNBA: fetching {len(remaining)}: {[tw.split('-')[-1] for tw in remaining]}")

    def fetch_url(url, retries=3):
        """Fetch with retry on 429."""
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                return urllib.request.urlopen(req, timeout=20, context=ctx).read().decode("utf-8", errors="ignore")
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    _time.sleep(3 * (attempt + 1))
                    continue
                return None
            except Exception:
                _time.sleep(1)
                continue
        return None

    # Find starting point — hashtag or known article
    start_url = None
    for tag_url in [
        "https://vnba.org.vn/vi/hashtag/ban-tin-tuan-vnba-24399",
        "https://vnba.org.vn/vi/tin-tuc/thong-tin-hoat-dong-ngan-hang",
    ]:
        html = fetch_url(tag_url)
        if html:
            articles = re.findall(r'/vi/[^"]*ban-tin-kinh-te-tai-chinh-tien-te-tuan-[^"]+\.htm', html)
            if articles:
                start_url = "https://vnba.org.vn" + sorted(set(articles))[-1]
                break
    if not start_url:
        for week_n in [4, 3, 5]:
            html = fetch_url(f"https://vnba.org.vn/vi/hashtag/kinh-te-tai-chinh-tien-te-tuan-{week_n}")
            if html:
                articles = re.findall(r'/vi/ban-tin-kinh-te-tai-chinh-tien-te-tuan-\d+-thang-\d+-\d+-\d+\.htm', html)
                if articles:
                    start_url = "https://vnba.org.vn" + sorted(set(articles))[-1]
                    break
    if not start_url:
        start_url = "https://vnba.org.vn/vi/ban-tin-kinh-te-tai-chinh-tien-te-tuan-4-thang-6-2026-22424.htm"

    # Chain crawl: follow sidebar backward
    current_url = start_url
    max_chain = 15  # safety limit

    for step in range(max_chain):
        if not remaining:
            break

        _time.sleep(1.5)  # rate limit protection
        html = fetch_url(current_url)
        if not html:
            continue

        # Extract CDN PDF
        cdn_match = re.search(r'(https://s-vnba-cdn\.aicms\.vn/[^"]+\.pdf)', html)
        if cdn_match:
            pdf_url = cdn_match.group(1)
            pdf_path = out_dir / f"vnba_tmp_{step}.pdf"
            txt_path = out_dir / f"vnba_tmp_{step}.txt"
            try:
                pdf_path.write_bytes(download_pdf(pdf_url))
                pdftotext(pdf_path, txt_path)
                text = txt_path.read_text(encoding="utf-8", errors="ignore")

                # Match against target weeks
                dates_found = re.findall(r"(\d{1,2})/(\d{1,2})/(\d{4})", text[:2000])
                # Also try title-based: "tuần N tháng M/YYYY"
                title_match = re.search(r'tuần\s*(\d+)\s*tháng\s*(\d+)\s*/?\s*(\d{4})', text[:500], re.I)

                matched = False
                for d_str, m_str, y_str in dates_found[:3]:
                    try:
                        d_val = _date(int(y_str), int(m_str), int(d_str))
                        iso = d_val.isocalendar()
                        tw_key = f"{iso[0]}-W{iso[1]:02d}"
                        if tw_key in remaining:
                            w_short = tw_key.split("-")[-1]
                            final_txt = out_dir / f"vnba_{w_short}.txt"
                            final_pdf = out_dir / f"vnba_{w_short}.pdf"
                            txt_path.rename(final_txt)
                            pdf_path.rename(final_pdf)
                            results[w_short] = final_txt
                            remaining.remove(tw_key)
                            print(f"    VNBA {w_short}: matched ({d_val})")
                            matched = True
                            break
                    except ValueError:
                        continue

                # Also check monthly variant: "tháng M + tuần 1 tháng M+1" = first week of M+1
                if not matched and title_match:
                    wn, mo, y = int(title_match.group(1)), int(title_match.group(2)), int(title_match.group(3))
                    if "tháng" in text[:200].lower() and "va" in text[:200].lower():
                        # Monthly variant — covers end of prev month + start of this month
                        approx_day = min((wn - 1) * 7 + 3, 25)
                        try:
                            iso = _date(y, mo, approx_day).isocalendar()
                            tw_key = f"{iso[0]}-W{iso[1]:02d}"
                            if tw_key in remaining:
                                w_short = tw_key.split("-")[-1]
                                final_txt = out_dir / f"vnba_{w_short}.txt"
                                final_pdf = out_dir / f"vnba_{w_short}.pdf"
                                txt_path.rename(final_txt)
                                pdf_path.rename(final_pdf)
                                results[w_short] = final_txt
                                remaining.remove(tw_key)
                                print(f"    VNBA {w_short}: matched (tuan {wn} thang {mo})")
                                matched = True
                        except ValueError:
                            pass

                if not matched:
                    txt_path.unlink(missing_ok=True)
                    pdf_path.unlink(missing_ok=True)
            except Exception:
                txt_path.unlink(missing_ok=True)
                pdf_path.unlink(missing_ok=True)

        # Find next (older) article in sidebar
        current_id_m = re.search(r'-(\d+)\.htm', current_url)
        if not current_id_m:
            break
        current_id = int(current_id_m.group(1))
        sidebar_links = re.findall(r'/vi/ban-tin-kinh-te-tai-chinh-tien-te-[^"]+\.htm', html)
        older = []
        for link in sidebar_links:
            id_m = re.search(r'-(\d+)\.htm', link)
            if id_m and int(id_m.group(1)) < current_id:
                older.append((int(id_m.group(1)), link))

        if older:
            # Go to the next most recent older article
            older.sort(key=lambda x: x[0], reverse=True)
            current_url = "https://vnba.org.vn" + older[0][1]
        else:
            break

    if remaining:
        print(f"  ⚠️ VNBA not found: {[tw.split('-')[-1] for tw in remaining]}")
    return results


def fetch_vnba_recent(out_dir: Path, count: int = 4) -> dict:
    """Fetch N most-recent VNBA weekly bulletins.

    Strategy: VNBA không có category page. Thay vào đó:
    1. Bắt đầu từ 1 bài biết gần nhất (hardcoded fallback hoặc từ hashtag)
    2. Scrape sidebar links từ bài đó → tìm các bài khác
    3. Sort by article ID (monotonic = chronological) → lấy N gần nhất
    4. Follow từng bài → extract CDN PDF → download
    """
    import ssl as _ssl
    ctx = _ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = _ssl.CERT_NONE

    # Bước 1: Tìm bài gần nhất — thử hashtag tuần 4, rồi tuần 3
    start_url = None
    for week_n in [4, 3, 5, 2]:
        hashtag_url = f"https://vnba.org.vn/vi/hashtag/kinh-te-tai-chinh-tien-te-tuan-{week_n}"
        try:
            req = urllib.request.Request(hashtag_url, headers={"User-Agent": USER_AGENT})
            html = urllib.request.urlopen(req, timeout=15, context=ctx).read().decode("utf-8", errors="ignore")
            articles = re.findall(r'/vi/ban-tin-kinh-te-tai-chinh-tien-te-tuan-\d+-thang-\d+-\d+-\d+\.htm', html)
            if articles:
                start_url = "https://vnba.org.vn" + sorted(set(articles))[-1]
                break
        except Exception:
            continue

    # Fallback: hardcoded bài gần nhất (update khi cần)
    if not start_url:
        start_url = "https://vnba.org.vn/vi/ban-tin-kinh-te-tai-chinh-tien-te-tuan-4-thang-6-2026-22424.htm"

    # Bước 2: Scrape sidebar từ bài gần nhất
    try:
        req = urllib.request.Request(start_url, headers={"User-Agent": USER_AGENT})
        html = urllib.request.urlopen(req, timeout=15, context=ctx).read().decode("utf-8", errors="ignore")
    except Exception:
        return {}

    sidebar_links = sorted(set(re.findall(r'/vi/ban-tin-kinh-te-tai-chinh-tien-te-[^"]+\.htm', html)))
    # Thêm chính bài start vào list
    start_path = "/" + start_url.split("/", 3)[-1]
    if start_path not in sidebar_links:
        sidebar_links.append(start_path)

    # Bước 3: Parse week/month/year/id → sort by ID
    parsed = []
    for link in sidebar_links:
        m = re.search(r'tuan-(\d+)-thang-(\d+)-(\d+)-(\d+)', link)
        if m:
            parsed.append({"link": link, "id": int(m.group(4)),
                          "week_n": int(m.group(1)), "month": int(m.group(2)), "year": int(m.group(3))})
            continue
        m2 = re.search(r'thang-(\d+)-va-tuan-1-thang-(\d+)-(\d+)-(\d+)', link)
        if m2:
            parsed.append({"link": link, "id": int(m2.group(4)),
                          "week_n": 1, "month": int(m2.group(2)), "year": int(m2.group(3))})

    parsed.sort(key=lambda x: x["id"], reverse=True)
    recent = parsed[:count]

    if len(recent) < count:
        print(f"  ⚠️ VNBA: chỉ tìm thấy {len(recent)} bài (cần {count})")

    # Bước 4: Fetch từng bài → extract CDN PDF → download + rename
    results = {}
    for item in recent:
        art_url = "https://vnba.org.vn" + item["link"]
        try:
            req = urllib.request.Request(art_url, headers={"User-Agent": USER_AGENT})
            art_html = urllib.request.urlopen(req, timeout=15, context=ctx).read().decode("utf-8", errors="ignore")
        except Exception:
            continue

        cdn_match = re.search(r'(https://s-vnba-cdn\.aicms\.vn/[^"]+\.pdf)', art_html)
        if not cdn_match:
            continue

        pdf_url = cdn_match.group(1)

        # Determine ISO week — for "thang-X-va-tuan-1-thang-Y" use day 3 of target month
        from datetime import date as _date
        if "thang-" in item["link"] and item["link"].count("thang-") > 1:
            # Monthly variant "thang-5-va-tuan-1-thang-6" → use day 3 of month Y (first ISO week)
            try:
                iso = _date(item["year"], item["month"], 3).isocalendar()
                week_short = f"W{iso[1]:02d}"
            except ValueError:
                week_short = f"tuan{item['week_n']}_thang{item['month']}"
        else:
            # Regular: use mid-week day to approximate ISO week
            approx_day = min((item["week_n"] - 1) * 7 + 3, 25)
            try:
                iso = _date(item["year"], item["month"], approx_day).isocalendar()
                week_short = f"W{iso[1]:02d}"
            except ValueError:
                week_short = f"tuan{item['week_n']}_thang{item['month']}"

        pdf_path = out_dir / f"vnba_{week_short}.pdf"
        txt_path = out_dir / f"vnba_{week_short}.txt"

        # Skip if already exists
        if txt_path.exists():
            print(f"  VNBA {week_short}: cached")
            results[f"vnba_{week_short}"] = txt_path
            continue

        try:
            pdf_path.write_bytes(download_pdf(pdf_url))
            pdftotext(pdf_path, txt_path)
            print(f"  VNBA {week_short}: fetched ({txt_path.stat().st_size:,} chars)")
            results[f"vnba_{week_short}"] = txt_path
        except Exception as e:
            print(f"  VNBA {week_short}: ERROR {e}")

    return results


def fetch_fred_series(series_id: str, weeks: int = 12) -> list[dict]:
    """Fetch FRED series observations for the last N weeks. Needs FRED_API_KEY."""
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        return []  # upstream_skip — caller handles
    end = date.today()
    start = end - timedelta(weeks=weeks)
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={api_key}&file_type=json"
        f"&observation_start={start.isoformat()}&observation_end={end.isoformat()}"
    )
    data = curl(url)
    payload = json.loads(data)
    return payload.get("observations", [])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", required=True, help="Target ISO week, e.g. 2026-W26")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--upstream-only", action="store_true")
    parser.add_argument(
        "--sbv-only",
        action="store_true",
        help="Fetch only the exact SBV week (used by the rolling-cache pipeline)",
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.upstream_only:
        weeks = enumerate_4_weeks(args.week)
        if args.sbv_only:
            weeks = [week for week in weeks if week.iso_week == args.week]
        print(f"Enumerated weeks: {[w.iso_week for w in weeks]}")
        failed = False
        for w in weeks:
            try:
                txt = fetch_sbv_week(w, out_dir)
                status = txt.name if txt else "SKIP (holiday?)"
                if args.sbv_only and txt is None:
                    failed = True
            except Exception as e:
                status = f"ERROR: {e}"
                failed = True
            print(f"  SBV {w.iso_week}: {status}")
        if args.sbv_only and failed:
            raise SystemExit(1)
        if not args.sbv_only:
            try:
                vbma = fetch_vbma_recent(out_dir)
                print(f"  VBMA: fetched {len(vbma)} PDFs")
            except Exception as e:
                print(f"  VBMA: ERROR: {e}")
            try:
                vnba = fetch_vnba_recent(out_dir)
                print(f"  VNBA: fetched {len(vnba)} PDFs")
            except Exception as e:
                print(f"  VNBA: ERROR: {e}")

    # Upstream (always attempt, gracefully skip if no key)
    if args.sbv_only:
        return
    fred_10y = fetch_fred_series("DGS10", weeks=12)
    print(f"  FRED DGS10: {len(fred_10y)} observations")
    fred_dxy = fetch_fred_series("DTWEXBGS", weeks=12)
    print(f"  FRED DXY: {len(fred_dxy)} observations")


if __name__ == "__main__":
    main()
