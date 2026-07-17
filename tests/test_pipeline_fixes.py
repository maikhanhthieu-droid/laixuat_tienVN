from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from extract_cards import parse_sbv_interbank_real
from run_pipeline import rolling_weeks


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
