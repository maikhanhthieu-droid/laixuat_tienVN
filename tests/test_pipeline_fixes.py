from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from extract_cards import parse_sbv_interbank_real
from run_pipeline import rolling_weeks
from verify_data import verify_report_v2


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
