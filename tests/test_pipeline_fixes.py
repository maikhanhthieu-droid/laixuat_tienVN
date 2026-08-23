from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from extract_cards import parse_sbv_interbank_real
from build_report_v2 import generate_fx_prose, generate_lnh_prose, generate_lstp_prose
from fetch_sources import WeekRange, download_pdf, fetch_sbv_week
from run_pipeline import rolling_weeks
from verify_data import classify_lnh_crosscheck, verify_report_v2


def test_lnh_crosscheck_warns_for_different_average_definitions():
    assert classify_lnh_crosscheck(5.0) == "OK"
    assert classify_lnh_crosscheck(22.0) == "WARNING"


def test_download_pdf_rejects_html_response(monkeypatch):
    monkeypatch.setattr(
        "fetch_sources.curl",
        lambda *args, **kwargs: b"<html>Request Rejected</html>",
    )
    with pytest.raises(RuntimeError, match="response is not a PDF"):
        download_pdf("https://example.invalid/report.pdf", retries=1)


def test_sbv_fetch_prefers_direct_document_url(monkeypatch, tmp_path):
    week = WeekRange(
        iso_week="2026-W32",
        monday=date(2026, 8, 3),
        friday=date(2026, 8, 7),
    )
    requested = []

    def fake_download(url, headers=None, **kwargs):
        requested.append(url)
        return b"%PDF-test"

    def fake_pdftotext(pdf_path, txt_path):
        txt_path.write_text("SBV fixture", encoding="utf-8")

    monkeypatch.setattr("fetch_sources.download_pdf", fake_download)
    monkeypatch.setattr("fetch_sources.pdftotext", fake_pdftotext)
    monkeypatch.setattr(
        "fetch_sources.curl",
        lambda *args, **kwargs: pytest.fail("article page should not be requested"),
    )

    result = fetch_sbv_week(week, tmp_path)

    assert result == tmp_path / "sbv_2026-W32.txt"
    assert requested == [
        "https://www.sbv.gov.vn/documents/20117/0/03-07.8.2026.pdf"
    ]


def test_v2_verification_reports_missing_required_sources(tmp_path):
    report = {
        "period": {"weeks_covered": ["2026-W32"]},
        "sections": {
            "lnh": {"data_summary": {}},
            "lstp": {"data_summary": {}},
            "fx": {"data_summary": {}},
        },
    }
    report_path = tmp_path / "report.json"
    cache = tmp_path / "cache"
    cache.mkdir()
    report_path.write_text(json.dumps(report), encoding="utf-8")

    results = verify_report_v2(report_path, cache)

    assert any(result.status == "MISSING_SOURCE" for result in results)


def test_parse_real_sbv_table_and_fx_range():
    text = (
        "Qua đêm 1 tuần 2 tuần 1 tháng 3 tháng 6 tháng 9 tháng\n"
        "VND 4,26 7,34 7,76 7,32 7,94 8,12 8,06\n"
        "Cuối ngày 26/06 ở mức 26.114/26.454"
    )
    parsed = parse_sbv_interbank_real(text)
    assert parsed["overnight"] == 4.26
    assert parsed["one_week"] == 7.34
    assert parsed["nine_month"] == 8.06
    assert parsed["fx_tm_low"] == 26114
    assert parsed["fx_tm_high"] == 26454

    hyphen = parse_sbv_interbank_real(
        "Tỷ giá giao dịch của các NHTM: 25.300 - 25.450"
    )
    assert hyphen["fx_tm_low"] == 25300
    assert hyphen["fx_tm_high"] == 25450


def test_rolling_weeks_handles_year_boundary():
    assert rolling_weeks("2026-W02") == [
        "2025-W51",
        "2025-W52",
        "2026-W01",
        "2026-W02",
    ]


def test_parse_real_sbv_table_with_wrapped_or_annotated_row():
    text = (
        "Qua đêm 1 tuần 2 tuần 1 tháng 3 tháng 6 tháng 9 tháng\n"
        "VND 3,90 5,14 6,20 7,93 ghi chú cuối dòng\n"
    )
    parsed = parse_sbv_interbank_real(text)
    assert parsed["overnight"] == 3.90
    assert parsed["one_week"] == 5.14
    assert parsed["one_month"] == 7.93


def test_verify_v2_compares_curve_to_latest_requested_week(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    vbma_text = (
        "28/6/2026  3.40%  3.50%  3.60%  4.20%  4.30% "
        "4.40%  4.50%  4.60%  4.70%\n"
    )
    (cache / "vbma_W28.txt").write_text(vbma_text, encoding="utf-8")

    curve = {
        "1N": 3.40,
        "2N": 3.50,
        "3N": 3.60,
        "5N": 4.20,
        "7N": 4.30,
        "10N": 4.40,
        "15N": 4.50,
        "20N": 4.60,
        "30N": 4.70,
    }
    report = {
        "period": {"weeks_covered": ["2026-W28"]},
        "sections": {
            "lnh": {"data_summary": {}},
            "lstp": {
                "data_summary": {
                    "y2_4w": [{"week": "W28", "value": 3.50}],
                    "y5_4w": [{"week": "W28", "value": 4.20}],
                    "y10_4w": [{"week": "W28", "value": 4.40}],
                    "curve_w26": curve,
                    "auction_w26": {},
                }
            },
            "fx": {"data_summary": {}},
        },
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    results = verify_report_v2(report_path, cache)
    curve_results = [
        result for result in results if result.card_key.startswith("curve_")
    ]
    assert len(curve_results) == 9
    assert all(result.week == "W28" for result in curve_results)
    assert all(result.status == "OK" for result in curve_results)


def test_lnh_narrative_reports_numeric_change_without_value_judgment():
    sbv = [
        {"overnight": 4.0, "one_week": 4.5, "one_month": 5.0},
        {"overnight": 4.1, "one_week": 4.8, "one_month": 5.1},
        {"overnight": 4.2, "one_week": 5.0, "one_month": 5.2},
        {"overnight": 4.3, "one_week": 6.0, "one_month": 5.3},
    ]
    vbma = [
        SimpleNamespace(
            interbank={
                "ON": {
                    "close": 3.5 + index * 0.1,
                    "tb5": 3.5 + index * 0.1,
                    "wow_bp": 10,
                    "mom_bp": 30,
                }
            },
            omo_outstanding=None,
        )
        for index in range(4)
    ]
    section = generate_lnh_prose(sbv, vbma, "2026-W28")
    detail = section["w26_detail"]
    assert "LNH 1 tuần bình quân SBV" in detail
    assert "+100bp so với tuần trước" in detail
    assert "tăng vọt" not in detail


def test_bond_narrative_uses_observed_direction_and_shape():
    vbma = []
    for index in range(4):
        vbma.append(
            SimpleNamespace(
                yields={
                    "2N": 3.50 - index * 0.02,
                    "5N": 4.20 - index * 0.05,
                    "10N": 4.40 - index * 0.10,
                },
                yields_wow_bp={},
                auction={},
                secondary_total=0,
                foreign_net_sell_week=0,
                foreign_net_sell_ytd=0,
            )
        )
    section = generate_lstp_prose(vbma, {}, "2026-W28")
    assert "LSTP 10 năm giảm" in section["overview"]
    assert "hình dạng quan sát" in section["overview"]
    assert "bình thường" not in section["overview"]


def test_missing_fx_is_not_reported_as_stable():
    sbv = [{}, {}, {}, {}]
    section = generate_fx_prose(sbv, None, None, "2026-W28")
    assert "Chưa đủ hai kỳ USD/VND" in section["overview"]
    assert "ổn định" not in section["overview"]
