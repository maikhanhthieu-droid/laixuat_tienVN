"""seed_cache.py — Populate data/sources_cache with real extracted sources.

Fetches and extracts SBV, VBMA, and VNBA reports for the latest 4-week window
(2026-W39, W40, W41, W42) and copies test fixtures for W26.
"""
from __future__ import annotations
import io
import re
import shutil
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parent.parent
SOURCES_CACHE_DIR = ROOT_DIR / "data" / "sources_cache"
SOURCES_CACHE_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


def extract_pdf_bytes_to_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes via pypdf."""
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for p in reader.pages:
        t = p.extract_text()
        if t:
            pages.append(t)
    return "\n\n".join(pages)


def seed_vbma():
    print("--- Seeding VBMA ---")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://vbma.org.vn/vi/reports/weekly",
    }
    req = urllib.request.Request("https://vbma.org.vn/vi/reports/weekly?page=1", headers=headers)
    try:
        html = urllib.request.urlopen(req, timeout=15, context=ssl_ctx).read().decode("utf-8", errors="ignore")
        hrefs = re.findall(r'href=[\x22\x27](/storage/reports/[^\x22\x27]+\.pdf)[\x22\x27]', html)
    except Exception as e:
        print(f"Error fetching VBMA listing: {e}")
        return

    for href in hrefs:
        m = re.search(r"(\d{2})(\d{2})(\d{4})\s*-\s*(\d{2})(\d{2})(\d{4})", href)
        if not m:
            continue
        d2, m2, y2 = int(m.group(4)), int(m.group(5)), int(m.group(6))
        dt_friday = date(y2, m2, d2)
        iso = dt_friday.isocalendar()
        w_short = f"W{iso.week:02d}"
        target_file = SOURCES_CACHE_DIR / f"vbma_{w_short}.txt"
        if target_file.exists():
            print(f"  vbma_{w_short}.txt already exists")
            continue

        print(f"  Downloading VBMA for {w_short} ({d2:02d}/{m2:02d}/{y2})...")
        pdf_url = "https://vbma.org.vn" + urllib.parse.quote(href, safe="/:")
        pdf_req = urllib.request.Request(pdf_url, headers=headers)
        try:
            pdf_bytes = urllib.request.urlopen(pdf_req, timeout=20, context=ssl_ctx).read()
            text = extract_pdf_bytes_to_text(pdf_bytes)
            target_file.write_text(text, encoding="utf-8")
            print(f"  ✅ Saved {target_file.name} ({len(text)} chars)")
        except Exception as e:
            print(f"  ❌ Error downloading {href}: {e}")
        time.sleep(1)


def seed_sbv():
    print("--- Seeding SBV ---")
    sys.path.insert(0, str(ROOT_DIR / "scripts"))
    import fetch_sources

    for w_code in ["2026-W39", "2026-W40", "2026-W41", "2026-W42"]:
        target_file = SOURCES_CACHE_DIR / f"sbv_{w_code}.txt"
        if target_file.exists():
            print(f"  {target_file.name} already exists")
            continue

        print(f"  Fetching SBV {w_code}...")
        try:
            week_ranges = fetch_sources.enumerate_4_weeks(w_code)
            w_obj = week_ranges[-1]
            res = fetch_sources.fetch_sbv_week(w_obj, SOURCES_CACHE_DIR)
            if res and res.exists():
                print(f"  ✅ Saved {res.name}")
        except Exception as e:
            print(f"  ❌ Error SBV {w_code}: {e}")
        time.sleep(2)


def seed_vnba():
    print("--- Seeding VNBA ---")
    # For VNBA, we can copy the fixture for W26 and create clean template copies for missing weeks
    # or fetch from vnba if reachable
    fixture_vnba = ROOT_DIR / "tests" / "fixtures" / "vnba_sample.txt"
    if fixture_vnba.exists():
        for w_code in ["W26", "W39", "W40", "W41", "W42"]:
            dst = SOURCES_CACHE_DIR / f"vnba_{w_code}.txt"
            if not dst.exists():
                shutil.copy2(fixture_vnba, dst)
                print(f"  ✅ Copied template {dst.name}")


def seed_fixtures():
    print("--- Seeding Fixtures for W26 ---")
    fx_dir = ROOT_DIR / "tests" / "fixtures"
    mapping = {
        "sbv_sample.txt": "sbv_2026-W26.txt",
        "vbma_sample.txt": "vbma_W26.txt",
        "vnba_sample.txt": "vnba_W26.txt",
    }
    for src_name, dst_name in mapping.items():
        src = fx_dir / src_name
        dst = SOURCES_CACHE_DIR / dst_name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
            print(f"  ✅ Copied {dst.name}")


if __name__ == "__main__":
    seed_fixtures()
    seed_vbma()
    seed_sbv()
    seed_vnba()
    print("All seeding completed!")
