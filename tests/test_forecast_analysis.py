from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from forecast_analysis import build_forecast


def test_forecast_returns_point_and_band_for_verified_series():
    report = {
        "sections": {
            "lnh": {
                "data_summary": {
                    "on_4w": [
                        {"week": "W25", "value": 3.90},
                        {"week": "W26", "value": 4.26},
                        {"week": "W27", "value": 4.75},
                        {"week": "W28", "value": 5.21},
                    ]
                }
            },
            "lstp": {
                "data_summary": {
                    "y10_4w": [
                        {"week": "W25", "value": 4.37},
                        {"week": "W26", "value": 4.38},
                        {"week": "W27", "value": 4.39},
                        {"week": "W28", "value": 4.40},
                    ]
                }
            },
            "fx": {
                "data_summary": {
                    "fx_mid_4w": [
                        {"week": "W25", "value": 26240},
                        {"week": "W26", "value": 26250},
                        {"week": "W27", "value": 26260},
                        {"week": "W28", "value": 26268},
                    ]
                }
            },
        }
    }
    result = build_forecast(report)
    assert result["scenario"] == "Căng ngắn hạn; dài hạn chưa xác nhận"
    lnh = next(item for item in result["metrics"] if item["key"] == "lnh_overnight")
    assert lnh["status"] == "ok"
    assert lnh["forecasts"]["4w"]["point"] > lnh["latest"]
    assert lnh["forecasts"]["4w"]["low"] < lnh["forecasts"]["4w"]["high"]
