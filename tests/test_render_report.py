from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from audit_gate import run_all_gates
from render_report import build_chart_configs, render_report
from test_telegram_publish import sample_report


def test_renderer_is_data_driven_and_balanced():
    report = sample_report()
    report["sections"]["lnh"]["overview"] = "LNH qua đêm tăng theo số liệu tuần."
    report["sections"]["lstp"]["overview"] = "Lợi suất 10 năm tăng 3 điểm cơ bản."
    report["sections"]["fx"]["overview"] = "USD/VND ở mức 26.268."

    rendered = render_report(report)

    assert "Tuần 28/2026" in rendered
    assert "2026-W26" not in rendered
    assert "5.21" in rendered
    assert rendered.count("<div") == rendered.count("</div>")
    assert rendered.count("<section") == rendered.count("</section>")


def test_chart_configs_use_report_series():
    charts = build_chart_configs(sample_report())
    lnh = next(item for item in charts if item["id"] == "chart-lnh")
    assert lnh["labels"][-1] == "Tuần 28"
    assert lnh["datasets"][0]["data"][-1] == 5.21


def test_rendered_report_passes_audit_gates(tmp_path):
    report = sample_report()
    report["sections"]["lnh"]["overview"] = "LNH qua đêm tăng theo số liệu tuần."
    report["sections"]["lstp"]["overview"] = "Lợi suất 10 năm tăng 3 điểm cơ bản."
    report["sections"]["fx"]["overview"] = "USD/VND ở mức 26.268."
    output = tmp_path / "report.html"
    output.write_text(render_report(report), encoding="utf-8")
    assert run_all_gates(output)
