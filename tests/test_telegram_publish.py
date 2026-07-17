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
        "verdict": "THẮT CHẶT NHẸ",
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
    assert metrics["lnh_now"] == 5.21
    assert round(metrics["lnh_delta_bp"]) == 131
    assert round(metrics["y10_delta_bp"]) == 3
    assert metrics["us10y_now"] == 4.37

    summary = build_summary(report, chart_data=chart_data)
    assert "Tuần 28/2026" in summary
    assert "5,21%" in summary
    assert "+131 đcb" in summary
    assert "4,40%" in summary
    assert "26.268" in summary
    assert "US 10Y" in summary
    assert "DXY proxy" in summary
    assert len(summary) <= 4096


def test_summary_includes_model_scenario_when_present():
    report = sample_report()
    report["analysis"] = {
        "scenario": "LNH tăng; LSTP dài hạn chưa xác nhận",
        "confidence": "trung bình",
    }
    summary = build_summary(report)
    assert "Ngoại suy thống kê 1–4 tuần" in summary
    assert "trung bình" in summary


def test_neutral_indicators_are_formula_only():
    report = sample_report()
    report["sections"]["lnh"]["data_summary"]["m1_4w"] = [
        {"week": "W28", "value": 7.32}
    ]
    report["sections"]["lstp"]["data_summary"]["y2_4w"] = [
        {"week": "W28", "value": 3.50}
    ]
    indicators = extract_neutral_indicators(report)
    assert any("1 tháng–ON" in item for item in indicators)
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
        "scenario": "LNH tăng; LSTP dài hạn chưa xác nhận",
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
