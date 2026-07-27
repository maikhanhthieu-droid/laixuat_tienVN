from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from telegram_publish import (
    build_summary,
    discover_chat_ids,
    extract_headlines,
    extract_neutral_indicators,
    publish_report,
)


def sample_report() -> dict:
    return {
        "report_id": "vn-rates-2026-W28",
        "period": {
            "week": 28,
            "year": 2026,
            "data_cutoff": "2026-07-10",
            "weeks_covered": [
                "2026-W25",
                "2026-W26",
                "2026-W27",
                "2026-W28",
            ],
        },
        "verdict": "PHÂN KỲ",
        "sections": {
            "lnh": {
                "data_summary": {
                    "on_4w": [
                        {"week": "W25", "value": None},
                        {"week": "W26", "value": None},
                        {"week": "W27", "value": 4.28},
                        {"week": "W28", "value": 3.87},
                    ],
                    "on_avg_4w": [
                        {"week": "W25", "value": 4.26},
                        {"week": "W26", "value": 4.45},
                        {"week": "W27", "value": 4.75},
                        {"week": "W28", "value": 5.21},
                    ],
                    "w1_4w": [
                        {"week": "W25", "value": 5.10},
                        {"week": "W26", "value": 5.45},
                        {"week": "W27", "value": 5.90},
                        {"week": "W28", "value": 6.20},
                    ],
                    "m1_4w": [
                        {"week": "W25", "value": 6.80},
                        {"week": "W26", "value": 7.00},
                        {"week": "W27", "value": 7.10},
                        {"week": "W28", "value": 7.32},
                    ],
                }
            },
            "lstp": {
                "data_summary": {
                    "y10_4w": [
                        {"week": "W25", "value": 4.37},
                        {"week": "W28", "value": 4.40},
                    ]
                }
            },
            "fx": {
                "data_summary": {
                    "fx_mid_4w": [
                        {"week": "W25", "value": 26240},
                        {"week": "W28", "value": 26268},
                    ]
                }
            },
        },
    }


def test_summary_uses_verified_json_values():
    report = sample_report()
    chart_data = {
        "us_10y": [{"date": "2026-07-10", "value": 4.37}],
        "dxy": [{"date": "2026-07-10", "value": 101.4}],
    }
    metrics = extract_headlines(report, chart_data=chart_data)
    assert metrics["lnh_now"] == 3.87
    assert metrics["lnh_points"] == 2
    assert round(metrics["lnh_delta_bp"]) == -41
    assert metrics["lnh_avg_now"] == 5.21
    assert metrics["lnh_avg_points"] == 4
    assert round(metrics["lnh_avg_delta_bp"]) == 95
    assert round(metrics["y10_delta_bp"]) == 3
    assert metrics["us10y_now"] == 4.37

    summary = build_summary(report, chart_data=chart_data)
    assert "Tuần 28/2026" in summary
    assert "LNH ON đóng cửa thứ Sáu (VBMA)" in summary
    assert "3,87%" in summary
    assert "-41 đcb/2 kỳ có dữ liệu" in summary
    assert "LNH ON bình quân tuần (SBV)" in summary
    assert "5,21%" in summary
    assert "+95 đcb/cửa sổ 4 kỳ" in summary
    assert "4,40%" in summary
    assert "26.268" in summary
    assert "US 10Y" in summary
    assert "DXY proxy" in summary
    assert len(summary) <= 4096


def test_summary_includes_model_scenario_when_present():
    report = sample_report()
    report["analysis"] = {
        "observed_state": "Kỳ gần nhất — LNH giảm; LSTP tăng",
        "base_case": "Nếu quan hệ 4 tuần tiếp diễn, đây là kịch bản có điều kiện.",
        "confidence": "trung bình",
        "confidence_basis": "2/3 chuỗi đủ điều kiện công bố dải số",
        "balance_notes": [
            "Tăng/giảm không tự động đồng nghĩa tốt/xấu; tác động khác nhau theo từng chủ thể."
        ],
    }
    summary = build_summary(report)
    assert "Trạng thái quan sát" in summary
    assert "Kịch bản mô hình tham khảo" in summary
    assert "trung bình" in summary
    assert "không phải xác suất" in summary
    assert "không tự động đồng nghĩa tốt/xấu" in summary


def test_neutral_indicators_are_formula_only():
    report = sample_report()
    report["sections"]["lstp"]["data_summary"]["y2_4w"] = [
        {"week": "W28", "value": 3.50}
    ]
    indicators = extract_neutral_indicators(report)
    assert "Chênh lệch LNH bình quân tuần SBV 1 tháng–ON: +211 đcb" in indicators
    assert any("10Y–2Y" in item for item in indicators)
    assert any("Biên độ USD/VND" in item for item in indicators)


class FakeClient:
    def __init__(self) -> None:
        self.messages = []
        self.documents = []

    def send_message(self, chat_id, text, report_url=None, disable_notification=False):
        self.messages.append((chat_id, text, report_url, disable_notification))
        return {"message_id": 42}

    def send_document(self, chat_id, document_path, caption, disable_notification=True):
        self.documents.append((chat_id, document_path, caption, disable_notification))
        return {"message_id": 43}


def test_discover_chat_ids_deduplicates_messages_and_channel_posts():
    class UpdateClient:
        @staticmethod
        def get_updates():
            return [
                {"message": {"chat": {"id": 123}}},
                {"message": {"chat": {"id": 123}}},
                {"channel_post": {"chat": {"id": -100456}}},
            ]

    assert discover_chat_ids(UpdateClient()) == ["123", "-100456"]


def test_publish_is_idempotent(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(sample_report(), ensure_ascii=False), encoding="utf-8")
    html_path = tmp_path / "report.html"
    html_path.write_text("<html></html>", encoding="utf-8")
    state_path = tmp_path / "state.json"
    client = FakeClient()

    first = publish_report(
        client,
        report_path,
        ["123"],
        html_path=html_path,
        report_url="https://example.test/report",
        state_path=state_path,
    )
    second = publish_report(
        client,
        report_path,
        ["123"],
        html_path=html_path,
        report_url="https://example.test/report",
        state_path=state_path,
    )

    assert first == {"123": "published"}
    assert second == {"123": "skipped (already published)"}
    assert len(client.messages) == 1
    assert len(client.documents) == 1
    assert state_path.exists()


def test_publish_without_document_sends_details_as_messages(tmp_path):
    report_path = tmp_path / "report.json"
    report = sample_report()
    report["analysis"] = {
        "observed_state": "Kỳ gần nhất — LNH giảm; LSTP tăng",
        "base_case": "Chưa công bố dải số.",
        "confidence": "trung bình",
        "metrics": [],
    }
    report["sections"]["lnh"]["overview"] = "LNH tăng theo chuỗi số liệu đã kiểm chứng."
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    html_path = tmp_path / "report.html"
    html_path.write_text("<html>should not be sent</html>", encoding="utf-8")
    client = FakeClient()

    statuses = publish_report(
        client,
        report_path,
        ["123"],
        html_path=html_path,
        state_path=tmp_path / "state.json",
        attach_document=False,
    )

    assert statuses == {"123": "published"}
    assert len(client.documents) == 0
    assert len(client.messages) >= 2
    assert any("Phân tích chi tiết" in item[1] for item in client.messages)
