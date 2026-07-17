#!/usr/bin/env python3
"""Publish a verified VN rates report to Telegram.

The module intentionally uses only Python's standard library. Secrets are read
from environment variables and are never accepted as command-line arguments,
which keeps them out of shell history and process listings.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TELEGRAM_TEXT_LIMIT = 4096


class TelegramError(RuntimeError):
    """Raised when Telegram rejects or cannot complete a request."""


def _latest_and_first(series: Iterable[dict[str, Any]]) -> tuple[float | None, float | None]:
    values = [
        item.get("value")
        for item in series
        if isinstance(item, dict) and isinstance(item.get("value"), (int, float))
    ]
    if not values:
        return None, None
    return float(values[-1]), float(values[0])


def _legacy_series(report: dict[str, Any], group: str, key: str) -> list[dict[str, Any]]:
    card = report.get(group, {}).get(key, {})
    values = card.get("values", [])
    return values if isinstance(values, list) else []


def extract_headlines(
    report: dict[str, Any], chart_data: dict[str, Any] | None = None
) -> dict[str, float | None]:
    """Extract headline metrics from both current and legacy report schemas."""
    sections = report.get("sections", {})
    if sections:
        lnh = sections.get("lnh", {}).get("data_summary", {}).get("on_4w", [])
        y10 = sections.get("lstp", {}).get("data_summary", {}).get("y10_4w", [])
        fx = sections.get("fx", {}).get("data_summary", {}).get("fx_mid_4w", [])
    else:
        lnh = _legacy_series(report, "group1_money_market", "interbank_on")
        y10 = _legacy_series(report, "group2_bonds", "gov_10y_yield")
        fx = _legacy_series(report, "group3_fx_global", "fx_tm_mid")

    lnh_now, lnh_then = _latest_and_first(lnh)
    y10_now, y10_then = _latest_and_first(y10)
    fx_now, fx_then = _latest_and_first(fx)
    chart_data = chart_data or {}
    us10y = chart_data.get("us_10y", [])
    dxy = chart_data.get("dxy", [])
    us10y_now = next(
        (
            row.get("value")
            for row in reversed(us10y)
            if isinstance(row, dict) and isinstance(row.get("value"), (int, float))
        ),
        None,
    ) if isinstance(us10y, list) else None
    dxy_now = next(
        (
            row.get("value")
            for row in reversed(dxy)
            if isinstance(row, dict) and isinstance(row.get("value"), (int, float))
        ),
        None,
    ) if isinstance(dxy, list) else None
    return {
        "lnh_now": lnh_now,
        "lnh_delta_bp": (
            (lnh_now - lnh_then) * 100
            if lnh_now is not None and lnh_then is not None
            else None
        ),
        "y10_now": y10_now,
        "y10_delta_bp": (
            (y10_now - y10_then) * 100
            if y10_now is not None and y10_then is not None
            else None
        ),
        "fx_now": fx_now,
        "fx_delta_pct": (
            (fx_now - fx_then) / fx_then * 100
            if fx_now is not None and fx_then not in (None, 0)
            else None
        ),
        "us10y_now": float(us10y_now) if us10y_now is not None else None,
        "dxy_now": float(dxy_now) if dxy_now is not None else None,
    }


def extract_neutral_indicators(report: dict[str, Any]) -> list[str]:
    """Derive formula-only indicators without policy or trading claims."""
    sections = report.get("sections", {})
    lnh = sections.get("lnh", {}).get("data_summary", {})
    bonds = sections.get("lstp", {}).get("data_summary", {})
    fx = sections.get("fx", {}).get("data_summary", {})
    on_now, _ = _latest_and_first(lnh.get("on_4w", []))
    m1_now, _ = _latest_and_first(lnh.get("m1_4w", []))
    y2_now, _ = _latest_and_first(bonds.get("y2_4w", []))
    y10_now, _ = _latest_and_first(bonds.get("y10_4w", []))
    fx_values = [
        float(item["value"])
        for item in fx.get("fx_mid_4w", [])
        if isinstance(item, dict) and isinstance(item.get("value"), (int, float))
    ]
    indicators = []
    if on_now is not None and m1_now is not None:
        indicators.append(
            f"Chênh lệch LNH 1 tháng–ON: {_format_signed((m1_now - on_now) * 100)} đcb"
        )
    if y2_now is not None and y10_now is not None:
        indicators.append(
            f"Độ dốc TPCP 10Y–2Y: {_format_signed((y10_now - y2_now) * 100)} đcb"
        )
    if len(fx_values) >= 2:
        fx_range_pct = (max(fx_values) - min(fx_values)) / fx_values[-1] * 100
        indicators.append(
            f"Biên độ USD/VND trong cửa sổ: {_format_decimal(fx_range_pct, 2)}%"
        )
    return indicators


def _format_decimal(value: float, decimals: int = 2) -> str:
    rendered = f"{value:,.{decimals}f}"
    return rendered.replace(",", "\0").replace(".", ",").replace("\0", ".")


def _format_signed(value: float, decimals: int = 0) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{_format_decimal(value, decimals)}"


def _week_label(report: dict[str, Any]) -> str:
    period = report.get("period", {})
    year = period.get("year")
    week = period.get("week")
    if isinstance(year, int) and isinstance(week, int):
        return f"Tuần {week:02d}/{year}"
    report_id = str(report.get("report_id", "Báo cáo tuần"))
    return report_id.replace("vn-rates-", "")


def build_summary(
    report: dict[str, Any], chart_data: dict[str, Any] | None = None
) -> str:
    """Build a compact, deterministic Telegram HTML summary."""
    metrics = extract_headlines(report, chart_data=chart_data)
    period = report.get("period", {})

    lines = [
        f"📊 <b>Lãi suất &amp; Tiền tệ Việt Nam — {html.escape(_week_label(report))}</b>",
        "",
        "📌 <b>Ảnh chụp định lượng</b>",
    ]
    if metrics["lnh_now"] is not None:
        detail = f"{_format_decimal(metrics['lnh_now'])}%"
        if metrics["lnh_delta_bp"] is not None:
            detail += f" ({_format_signed(metrics['lnh_delta_bp'])} đcb/4 tuần)"
        lines.append(f"💧 <b>LNH qua đêm:</b> {detail}")
    if metrics["y10_now"] is not None:
        detail = f"{_format_decimal(metrics['y10_now'])}%"
        if metrics["y10_delta_bp"] is not None:
            detail += f" ({_format_signed(metrics['y10_delta_bp'])} đcb/4 tuần)"
        lines.append(f"📈 <b>LSTP 10 năm:</b> {detail}")
    if metrics["fx_now"] is not None:
        detail = _format_decimal(metrics["fx_now"], 0)
        if metrics["fx_delta_pct"] is not None:
            detail += f" ({_format_signed(metrics['fx_delta_pct'], 2)}%/4 tuần)"
        lines.append(f"💱 <b>USD/VND:</b> {detail}")
    if metrics["us10y_now"] is not None:
        lines.append(f"🌐 <b>US 10Y:</b> {_format_decimal(metrics['us10y_now'])}%")
    if metrics["dxy_now"] is not None:
        lines.append(f"💵 <b>DXY proxy:</b> {_format_decimal(metrics['dxy_now'])}")
    for indicator in extract_neutral_indicators(report):
        lines.append(f"• {html.escape(indicator)}")

    cutoff = period.get("data_cutoff")
    if cutoff:
        lines.extend(["", f"🗓 <b>Chốt dữ liệu:</b> {html.escape(str(cutoff))}"])
    lines.extend(
        [
            "✅ Báo cáo chỉ được phát sau khi vượt kiểm chứng dữ liệu và audit.",
            "",
            "<i>Nội dung tổng hợp số liệu, không phải khuyến nghị đầu tư.</i>",
        ]
    )
    analysis = report.get("analysis", {})
    scenario = analysis.get("scenario") if isinstance(analysis, dict) else None
    if scenario:
        lines.insert(
            max(len(lines) - 3, 0),
            f"🔎 <b>Ngoại suy thống kê 1–4 tuần:</b> {html.escape(str(scenario))}",
        )
        confidence = analysis.get("confidence")
        if confidence:
            lines.insert(
                max(len(lines) - 3, 0),
                f"Độ tin cậy mô hình: {html.escape(str(confidence))}",
            )
    text = "\n".join(lines)
    if len(text) > TELEGRAM_TEXT_LIMIT:
        text = text[: TELEGRAM_TEXT_LIMIT - 1] + "…"
    return text


def _decode_response(method: str, response_bytes: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(response_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TelegramError(f"{method} returned an invalid response") from exc
    if not payload.get("ok"):
        description = payload.get("description", "unknown Telegram error")
        raise TelegramError(f"{method} failed: {description}")
    result = payload.get("result")
    return result if isinstance(result, dict) else {"result": result}


class TelegramClient:
    """Small Telegram Bot API client with secret-safe errors."""

    def __init__(
        self,
        token: str,
        timeout: float = 30,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        if not token:
            raise ValueError("Telegram token is empty")
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._timeout = timeout
        self._opener = opener

    def _open(self, method: str, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with self._opener(request, timeout=self._timeout) as response:
                return _decode_response(method, response.read())
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read()
                return _decode_response(method, body)
            except TelegramError:
                raise
            except Exception as parse_exc:
                raise TelegramError(f"{method} failed with HTTP {exc.code}") from parse_exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", "network error")
            raise TelegramError(f"{method} network error: {reason}") from exc

    def _json_request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self._base_url}/{method}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        return self._open(method, request)

    def send_message(
        self,
        chat_id: str,
        text: str,
        report_url: str | None = None,
        disable_notification: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "disable_notification": disable_notification,
        }
        if report_url:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": "Mở dashboard đầy đủ", "url": report_url}]
                ]
            }
        return self._json_request("sendMessage", payload)

    def send_document(
        self,
        chat_id: str,
        document_path: Path,
        caption: str,
        disable_notification: bool = True,
    ) -> dict[str, Any]:
        boundary = f"----vn-rates-{uuid.uuid4().hex}"
        chunks: list[bytes] = []

        def add_field(name: str, value: str) -> None:
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                    value.encode("utf-8"),
                    b"\r\n",
                ]
            )

        add_field("chat_id", chat_id)
        add_field("caption", caption)
        add_field("parse_mode", "HTML")
        add_field("disable_notification", "true" if disable_notification else "false")
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    'Content-Disposition: form-data; name="document"; '
                    f'filename="{document_path.name}"\r\n'
                ).encode(),
                b"Content-Type: text/html; charset=utf-8\r\n\r\n",
                document_path.read_bytes(),
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        request = urllib.request.Request(
            f"{self._base_url}/sendDocument",
            data=b"".join(chunks),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        return self._open("sendDocument", request)

    def get_updates(self) -> list[dict[str, Any]]:
        result = self._json_request(
            "getUpdates",
            {
                "limit": 100,
                "timeout": 0,
                "allowed_updates": ["message", "channel_post"],
            },
        )
        updates = result.get("result", [])
        return updates if isinstance(updates, list) else []


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"deliveries": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"deliveries": {}}
    if not isinstance(state, dict):
        return {"deliveries": {}}
    state.setdefault("deliveries", {})
    return state


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f"{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as temp:
            json.dump(state, temp, ensure_ascii=False, indent=2)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def report_fingerprint(
    report_path: Path,
    html_path: Path | None,
    chart_data_path: Path | None,
    report_url: str | None,
    attach_document: bool = True,
) -> str:
    digest = hashlib.sha256()
    digest.update(report_path.read_bytes())
    if html_path and html_path.exists():
        digest.update(html_path.read_bytes())
    if chart_data_path and chart_data_path.exists():
        digest.update(chart_data_path.read_bytes())
    digest.update((report_url or "").encode("utf-8"))
    digest.update(f"attach_document={attach_document}".encode("utf-8"))
    return digest.hexdigest()


def parse_chat_ids(explicit: list[str] | None = None) -> list[str]:
    candidates: list[str] = []
    if explicit:
        candidates.extend(explicit)
    for env_name in ("TELEGRAM_CHAT_IDS", "TELEGRAM_CHAT_ID"):
        raw = os.environ.get(env_name, "")
        candidates.extend(item.strip() for item in raw.split(",") if item.strip())
    return list(dict.fromkeys(candidates))


def discover_chat_ids(client: TelegramClient) -> list[str]:
    """Discover chat IDs from pending /start or channel updates."""
    found: list[str] = []
    for update in client.get_updates():
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is not None:
            found.append(str(chat_id))
    return list(dict.fromkeys(found))


def _detail_messages(report: dict[str, Any]) -> list[str]:
    """Render the report body as Telegram-safe text messages."""
    lines = ["📚 <b>Phân tích chi tiết</b>"]
    analysis = report.get("analysis", {})
    if isinstance(analysis, dict):
        lines.extend(
            [
                "",
                f"🔎 <b>Ngoại suy thống kê:</b> {html.escape(str(analysis.get('scenario', 'chưa đủ dữ liệu')))}",
                f"Độ tin cậy mô hình: {html.escape(str(analysis.get('confidence', 'thấp')))}",
            ]
        )
        for metric in analysis.get("metrics", []):
            if not isinstance(metric, dict) or metric.get("status") != "ok":
                continue
            four_week = metric.get("forecasts", {}).get("4w", {})
            unit = str(metric.get("unit", ""))
            suffix = f" {unit}" if unit else ""
            lines.append(
                f"• <b>{html.escape(str(metric.get('label')))}:</b> "
                f"{html.escape(str(metric.get('signal')))}; "
                f"4 tuần {html.escape(str(four_week.get('low')))}–"
                f"{html.escape(str(four_week.get('high')))}{html.escape(suffix)} "
                f"(tin cậy {html.escape(str(metric.get('confidence')))})"
            )

    section_labels = {
        "lnh": "LNH & OMO",
        "lstp": "Trái phiếu Chính phủ",
        "fx": "Tỷ giá & Ngoại hối",
        "global": "Bối cảnh toàn cầu",
        "vn": "Bối cảnh Việt Nam",
    }
    preferred = [
        "overview",
        "w26_detail",
        "volume_note",
        "auction_text",
        "secondary_text",
        "pairs_text",
        "cb_text",
        "govy_text",
        "eq_text",
        "comm_text",
        "bank_text",
        "gold_text",
        "cpi_text",
    ]
    for key, label in section_labels.items():
        section = report.get("sections", {}).get(key, {})
        if not isinstance(section, dict):
            continue
        values = [
            str(section[field]).strip()
            for field in preferred
            if isinstance(section.get(field), str) and section[field].strip()
        ]
        if not values:
            continue
        lines.extend(["", f"<b>{html.escape(label)}</b>"])
        lines.extend(html.escape(value) for value in values)

    # Split on line boundaries so Telegram never rejects a long report.
    chunks: list[str] = []
    current = ""
    max_length = TELEGRAM_TEXT_LIMIT - 150
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if current and len(candidate) > max_length:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def publish_report(
    client: TelegramClient,
    report_path: Path,
    chat_ids: list[str],
    html_path: Path | None = None,
    chart_data_path: Path | None = None,
    report_url: str | None = None,
    state_path: Path | None = None,
    force: bool = False,
    attach_document: bool = True,
    disable_notification: bool = False,
) -> dict[str, str]:
    """Publish to all chats and return a per-chat delivery status."""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    chart_data = None
    if chart_data_path and chart_data_path.exists():
        chart_data = json.loads(chart_data_path.read_text(encoding="utf-8"))
    summary = build_summary(report, chart_data=chart_data)
    fingerprint = report_fingerprint(
        report_path, html_path, chart_data_path, report_url, attach_document
    )
    state = _load_state(state_path) if state_path else {"deliveries": {}}
    deliveries = state.setdefault("deliveries", {})
    statuses: dict[str, str] = {}

    for chat_id in chat_ids:
        prior = deliveries.get(chat_id, {})
        if not force and prior.get("fingerprint") == fingerprint:
            statuses[chat_id] = "skipped (already published)"
            continue

        message = client.send_message(
            chat_id,
            summary,
            report_url=report_url,
            disable_notification=disable_notification,
        )
        if attach_document and html_path and html_path.exists():
            client.send_document(
                chat_id,
                html_path,
                caption=f"📎 Báo cáo đầy đủ — {html.escape(_week_label(report))}",
            )
        elif not attach_document:
            for detail in _detail_messages(report):
                client.send_message(
                    chat_id,
                    detail,
                    disable_notification=disable_notification,
                )

        deliveries[chat_id] = {
            "fingerprint": fingerprint,
            "report_id": report.get("report_id"),
            "message_id": message.get("message_id"),
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
        statuses[chat_id] = "published"
        if state_path:
            _save_state(state_path, state)

    return statuses


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish an audited VN rates report to Telegram"
    )
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--html", type=Path)
    parser.add_argument("--chart-data", type=Path)
    parser.add_argument("--report-url", default=os.environ.get("REPORT_URL"))
    parser.add_argument("--chat-id", action="append", dest="chat_ids")
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-document", action="store_true")
    parser.add_argument("--silent", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated message without contacting Telegram",
    )
    args = parser.parse_args()

    if not args.report.exists():
        parser.error(f"report file not found: {args.report}")
    if args.html and not args.html.exists():
        parser.error(f"HTML file not found: {args.html}")
    if args.chart_data and not args.chart_data.exists():
        parser.error(f"chart data file not found: {args.chart_data}")

    report = json.loads(args.report.read_text(encoding="utf-8"))
    chart_data = (
        json.loads(args.chart_data.read_text(encoding="utf-8"))
        if args.chart_data
        else None
    )
    chat_ids = parse_chat_ids(args.chat_ids)
    if args.dry_run:
        print(build_summary(report, chart_data=chart_data))
        print(f"\nRecipients: {', '.join(chat_ids) if chat_ids else '(not configured)'}")
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        parser.error("TELEGRAM_BOT_TOKEN is not set")
    state_path = args.state_file or args.report.parent / ".telegram_publish_state.json"
    client = TelegramClient(token)
    if not chat_ids:
        state = _load_state(state_path)
        chat_ids = list(state.get("deliveries", {}).keys())
    if not chat_ids:
        try:
            chat_ids = discover_chat_ids(client)
        except TelegramError as exc:
            print(f"Telegram chat discovery failed: {exc}", file=sys.stderr)
            return 1
    if not chat_ids:
        print(
            "No Telegram chat found. Send /start to the bot once, then rerun.",
            file=sys.stderr,
        )
        return 1
    if len(chat_ids) > 1 and not args.chat_ids and not os.environ.get(
        "TELEGRAM_CHAT_ID"
    ) and not os.environ.get("TELEGRAM_CHAT_IDS"):
        print(
            "Multiple Telegram chats found; set TELEGRAM_CHAT_ID explicitly.",
            file=sys.stderr,
        )
        return 1

    try:
        statuses = publish_report(
            client,
            args.report,
            chat_ids,
            html_path=args.html,
            chart_data_path=args.chart_data,
            report_url=args.report_url,
            state_path=state_path,
            force=args.force,
            attach_document=not args.no_document,
            disable_notification=args.silent,
        )
    except (OSError, json.JSONDecodeError, TelegramError) as exc:
        print(f"Telegram publish failed: {exc}", file=sys.stderr)
        return 1

    for chat_id, status in statuses.items():
        print(f"{chat_id}: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
