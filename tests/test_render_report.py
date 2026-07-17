from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from audit_gate import run_all_gates
from render_report import build_chart_configs, render_report
from test_telegram_publish import sample_report


def sample_chart_data() -> dict:
    rows = []
    dates = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"]
    for index, date in enumerate(dates):
        rows.extend(
            [
                {"date": date, "tenor": "2Y", "yield": 3.40 + index * 0.01},
                {"date": date, "tenor": "5Y", "yield": 4.10 + index * 0.01},
                {"date": date, "tenor": "10Y", "yield": 4.40 + index * 0.01},
            ]
        )
    return {
        "yields": rows,
        "auctions": [
            {"date": dates[0], "tenor": "5Y", "win_pct": 25.0},
            {"date": dates[1], "tenor": "5Y", "win_pct": 30.0},
            {"date": dates[0], "tenor": "10Y", "win_pct": 40.0},
            {"date": dates[1], "tenor": "10Y", "win_pct": 45.0},
        ],
        "us_10y": [
            {"date": date, "value": 4.20 + index * 0.01}
            for index, date in enumerate(dates)
        ],
        "dxy": [
            {"date": date, "value": 101.0 + index * 0.1}
            for index, date in enumerate(dates)
        ],
    }


def test_renderer_is_data_driven_and_balanced():
    report = sample_report()
    report["sections"]["lstp"]["data_summary"].update(
        {
            "y2_4w": [
                {"week": "W25", "value": 3.40},
                {"week": "W28", "value": 3.43},
            ],
            "y5_4w": [
                {"week": "W25", "value": 4.10},
                {"week": "W28", "value": 4.13},
            ],
        }
    )
    report["sections"]["lnh"]["overview"] = "LNH qua đêm tăng theo số liệu tuần."
    report["sections"]["lstp"]["overview"] = "Lợi suất 10 năm tăng 3 điểm cơ bản."
    report["sections"]["fx"]["overview"] = "USD/VND ở mức 26.268."
    report["sections"]["global"] = {}

    rendered = render_report(report, chart_data=sample_chart_data())

    assert "Tuần 28/2026" in rendered
    assert "2026-W26" not in rendered
    assert "5.21" in rendered
    assert rendered.count('<div class="chart-hint">') == 9
    assert rendered.count("<div") == rendered.count("</div>")
    assert rendered.count("<section") == rendered.count("</section>")


def test_chart_configs_use_report_series():
    report = sample_report()
    report["sections"]["lstp"]["data_summary"].update(
        {
            "y2_4w": [{"week": "W25", "value": 3.40}],
            "y5_4w": [{"week": "W25", "value": 4.10}],
        }
    )
    charts = build_chart_configs(report, chart_data=sample_chart_data())
    lnh = next(item for item in charts if item["id"] == "chart-lnh")
    assert lnh["labels"][-1] == "Tuần 28"
    assert lnh["datasets"][0]["data"][-1] == 5.21
    assert len(charts) == 9
    assert {item["id"] for item in charts} >= {
        "chart-hnx-yields",
        "chart-auction",
        "chart-slope",
        "chart-convexity",
        "chart-us10y",
        "chart-dxy",
    }


def test_rendered_report_passes_audit_gates(tmp_path):
    report = sample_report()
    report["sections"]["lstp"]["data_summary"].update(
        {
            "y2_4w": [{"week": "W25", "value": 3.40}],
            "y5_4w": [{"week": "W25", "value": 4.10}],
        }
    )
    report["sections"]["lnh"]["overview"] = "LNH qua đêm tăng theo số liệu tuần."
    report["sections"]["lstp"]["overview"] = "Lợi suất 10 năm tăng 3 điểm cơ bản."
    report["sections"]["fx"]["overview"] = "USD/VND ở mức 26.268."
    report["sections"]["global"] = {}
    output = tmp_path / "report.html"
    output.write_text(
        render_report(report, chart_data=sample_chart_data()), encoding="utf-8"
    )
    assert run_all_gates(output)
