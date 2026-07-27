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
    assert "Kỳ gần nhất" in result["observed_state"]
    assert "LNH ON đóng cửa thứ Sáu (VBMA): tăng" in result["observed_state"]
    assert "Nếu quan hệ trong cửa sổ 4 tuần tiếp diễn" in result["base_case"]
    assert "không phải xác suất" in result["balance_notes"][1]
    lnh = next(item for item in result["metrics"] if item["key"] == "lnh_overnight")
    assert lnh["status"] == "ok"
    assert lnh["forecast_status"] == "published"
    assert lnh["show_numeric_forecast"] is True
    assert lnh["forecasts"]["4w"]["point"] > lnh["latest"]
    assert lnh["forecasts"]["4w"]["low"] < lnh["forecasts"]["4w"]["high"]


def test_headline_direction_uses_latest_observed_move_not_regression_slope():
    report = {
        "sections": {
            "lnh": {
                "data_summary": {
                    "on_4w": [
                        {"week": "W25", "value": 3.00},
                        {"week": "W26", "value": 4.00},
                        {"week": "W27", "value": 5.00},
                        {"week": "W28", "value": 4.20},
                    ]
                }
            },
            "lstp": {"data_summary": {}},
            "fx": {"data_summary": {}},
        }
    }
    metric = build_forecast(report)["metrics"][0]
    assert metric["signal"] == "giảm"
    assert metric["trend_signal"] == "tăng"
    assert metric["observed_change"] == -0.8
    assert metric["direction_consistent"] is False
    assert metric["forecast_status"] == "direction_conflict"
    assert metric["confidence"] == "thấp"
    assert metric["show_numeric_forecast"] is False


def test_low_confidence_metric_suppresses_numeric_publication():
    report = {
        "sections": {
            "lnh": {
                "data_summary": {
                    "on_4w": [
                        {"week": "W27", "value": 4.28},
                        {"week": "W28", "value": 3.87},
                    ]
                }
            },
            "lstp": {"data_summary": {}},
            "fx": {"data_summary": {}},
        }
    }
    metric = build_forecast(report)["metrics"][0]
    assert metric["signal"] == "giảm"
    assert metric["confidence"] == "thấp"
    assert metric["forecast_status"] == "insufficient_data"
    assert metric["show_numeric_forecast"] is False


def test_assessment_is_neutral_not_a_good_bad_label():
    report = {
        "sections": {
            "lnh": {
                "data_summary": {
                    "on_4w": [
                        {"week": "W25", "value": 3.00},
                        {"week": "W26", "value": 3.30},
                        {"week": "W27", "value": 3.60},
                        {"week": "W28", "value": 3.90},
                    ]
                }
            },
            "lstp": {"data_summary": {}},
            "fx": {"data_summary": {}},
        }
    }
    result = build_forecast(report)
    metric = result["metrics"][0]
    assert "không tự động là tốt hoặc xấu" in metric["neutral_assessment"]
    assert result["confidence"] == "thấp"
    assert "1/3 chuỗi đủ điều kiện" in result["confidence_basis"]
