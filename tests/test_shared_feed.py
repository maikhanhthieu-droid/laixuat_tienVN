from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from build_shared_feed import SCHEMA_VERSION, build_feed


def test_feed_keeps_vbma_close_and_sbv_average_distinct():
    report = {
        "period": {
            "data_cutoff": "2026-07-17",
            "weeks_covered": ["2026-W28", "2026-W29"],
        },
        "sections": {
            "lnh": {
                "data_summary": {
                    "on_4w": [{"week": "W29", "value": 3.87}],
                    "on_avg_4w": [{"week": "W29", "value": 5.21}],
                }
            },
            "lstp": {"data_summary": {"y10_4w": []}},
            "fx": {"data_summary": {"fx_mid_4w": []}},
        },
    }
    feed = build_feed(report)
    assert feed["schema_version"] == SCHEMA_VERSION
    close = feed["facts"]["interbank_overnight_close"]
    average = feed["facts"]["interbank_overnight_weekly_average"]
    assert close["value"] == 3.87
    assert close["definition"] == "VBMA Friday close"
    assert average["value"] == 5.21
    assert average["definition"] == "SBV weekly average"
    assert feed["quality"]["ai_output_included"] is False
