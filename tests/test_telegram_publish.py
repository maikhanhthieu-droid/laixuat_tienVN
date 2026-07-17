from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from telegram_publish import build_summary, extract_headlines, publish_report


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
