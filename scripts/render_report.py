#!/usr/bin/env python3
"""Render a compact, data-driven HTML report from report.json.

Unlike the legacy demo renderer, this module contains no week-specific values.
Every headline, narrative and chart is derived from the verified JSON artifact.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


SECTION_META = {
    "lnh": ("01", "Liên ngân hàng & OMO", "SBV · VBMA"),
    "lstp": ("02", "Trái phiếu Chính phủ", "VBMA · HNX"),
    "fx": ("03", "Tỷ giá & Ngoại hối", "SBV · VBMA"),
    "global": ("04", "Bối cảnh toàn cầu", "VNBA · FRED"),
    "vn": ("05", "Bối cảnh Việt Nam", "VNBA"),
}


def _safe_text(value: Any) -> str:
    return html.escape(str(value)) if value not in (None, "") else ""


def _week_label(report: dict[str, Any]) -> str:
    period = report.get("period", {})
    year, week = period.get("year"), period.get("week")
    if isinstance(year, int) and isinstance(week, int):
        return f"Tuần {week:02d}/{year}"
    return str(report.get("report_id", "Báo cáo tuần")).replace("vn-rates-", "")


def _chart_label(raw: Any) -> str:
    label = str(raw)
    if label.startswith("W") and label[1:].isdigit():
        return f"Tuần {int(label[1:])}"
    if "-W" in label:
        year, week = label.split("-W", 1)
        if week.isdigit():
            return f"Tuần {int(week)}/{year}"
    return label


def _series(
    section: dict[str, Any], key: str
) -> tuple[list[str], list[float | None]]:
    raw = section.get("data_summary", {}).get(key, [])
    labels: list[str] = []
    values: list[float | None] = []
    if not isinstance(raw, list):
        return labels, values
    for point in raw:
        if not isinstance(point, dict):
            continue
        labels.append(_chart_label(point.get("week", "")))
        value = point.get("value")
        values.append(float(value) if isinstance(value, (int, float)) else None)
    return labels, values


def build_chart_configs(report: dict[str, Any]) -> list[dict[str, Any]]:
    sections = report.get("sections", {})
    charts: list[dict[str, Any]] = []

    lnh = sections.get("lnh", {})
    labels, on_values = _series(lnh, "on_4w")
    _, w1_values = _series(lnh, "w1_4w")
    _, m1_values = _series(lnh, "m1_4w")
    if labels:
        charts.append(
            {
                "id": "chart-lnh",
                "section": "lnh",
                "title": "Lãi suất liên ngân hàng VND",
                "labels": labels,
                "datasets": [
                    {"label": "Qua đêm", "data": on_values, "color": "#8b5cf6"},
                    {"label": "1 tuần", "data": w1_values, "color": "#ec4899"},
                    {"label": "1 tháng", "data": m1_values, "color": "#06b6d4"},
                ],
            }
        )

    bonds = sections.get("lstp", {})
    labels, y2 = _series(bonds, "y2_4w")
    _, y5 = _series(bonds, "y5_4w")
    _, y10 = _series(bonds, "y10_4w")
    if labels:
        charts.append(
            {
                "id": "chart-yields",
                "section": "lstp",
                "title": "Lợi suất TPCP",
                "labels": labels,
                "datasets": [
                    {"label": "2 năm", "data": y2, "color": "#10b981"},
                    {"label": "5 năm", "data": y5, "color": "#f59e0b"},
                    {"label": "10 năm", "data": y10, "color": "#ef4444"},
                ],
            }
        )

    fx = sections.get("fx", {})
    labels, fx_values = _series(fx, "fx_mid_4w")
    if labels:
        charts.append(
            {
                "id": "chart-fx",
                "section": "fx",
                "title": "USD/VND thương mại (giá giữa)",
                "labels": labels,
                "datasets": [
                    {"label": "USD/VND", "data": fx_values, "color": "#06b6d4"}
                ],
            }
        )
    return charts


def _render_prose(section: dict[str, Any]) -> str:
    preferred = [
        "overview",
        "w26_detail",
        "volume_note",
        "auction_text",
        "secondary_text",
        "pairs_text",
        "cb_text",
        "govy_text",
        "eq_text",
        "comm_text",
        "bank_text",
        "gold_text",
        "cpi_text",
    ]
    paragraphs = []
    seen: set[str] = set()
    for key in preferred:
        value = section.get(key)
        if not isinstance(value, str) or not value.strip() or value in seen:
            continue
        seen.add(value)
        paragraphs.append(f"<p>{_safe_text(value)}</p>")
    if not paragraphs:
        paragraphs.append("<p>Chưa có dữ liệu công bố cho nhóm này.</p>")
    return "\n".join(paragraphs)


def render_report(report: dict[str, Any]) -> str:
    sections = report.get("sections", {})
    chart_configs = build_chart_configs(report)
    charts_by_section: dict[str, list[dict[str, Any]]] = {}
    for chart in chart_configs:
        charts_by_section.setdefault(chart["section"], []).append(chart)

    tabs = []
    section_html = []
    first = True
    for key, (number, title, sources) in SECTION_META.items():
        if key not in sections:
            continue
        active = " active" if first else ""
        tabs.append(
            f'<button class="tab{active}" data-target="{key}">{_safe_text(title)}</button>'
        )
        chart_cards = "\n".join(
            (
                '<div class="chart-card">'
                f'<h3>{_safe_text(chart["title"])}</h3>'
                f'<div class="chart-wrap"><canvas id="{chart["id"]}"></canvas></div>'
                "</div>"
            )
            for chart in charts_by_section.get(key, [])
        )
        section_html.append(
            f"""
<section class="report-section{active}" id="{key}">
  <header class="section-header">
    <span class="section-number">{number}</span>
    <div><h2>{_safe_text(title)}</h2><small>{_safe_text(sources)}</small></div>
  </header>
  <article class="prose-card">{_render_prose(sections[key])}</article>
  {chart_cards}
</section>"""
        )
        first = False

    period = report.get("period", {})
    cutoff = _safe_text(period.get("data_cutoff", "—"))
    verdict = _safe_text(report.get("verdict", "CHƯA XÁC ĐỊNH"))
    chart_json = json.dumps(chart_configs, ensure_ascii=False)

    return f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VN Rates Weekly — {_safe_text(_week_label(report))}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.9/dist/chart.umd.min.js"></script>
<style>
:root{{--bg:#070b16;--card:#10182b;--line:#25324c;--text:#edf2ff;--muted:#93a4c3;--accent:#8b5cf6;--accent2:#06b6d4}}
*{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(145deg,#070b16,#10152a);color:var(--text);font:15px/1.7 Inter,system-ui,sans-serif}}
.wrap{{max-width:1080px;margin:auto;padding:28px 18px 72px}} .hero,.prose-card,.chart-card{{background:rgba(16,24,43,.92);border:1px solid var(--line);border-radius:18px}}
.hero{{padding:30px;margin-bottom:18px}} h1{{font-size:clamp(25px,5vw,42px);line-height:1.12;margin:0 0 10px}} .meta{{display:flex;gap:10px;flex-wrap:wrap;color:var(--muted)}}
.badge{{padding:6px 12px;border:1px solid var(--line);border-radius:999px}} .verdict{{color:#fff;background:linear-gradient(90deg,var(--accent),#ec4899);border:0}}
.tabs{{display:flex;gap:8px;overflow:auto;padding:10px 0 18px;position:sticky;top:0;background:rgba(7,11,22,.92);backdrop-filter:blur(12px);z-index:10}}
.tab{{white-space:nowrap;border:1px solid var(--line);background:#0d1425;color:var(--muted);padding:9px 14px;border-radius:999px;cursor:pointer}} .tab.active{{background:var(--accent);color:#fff}}
.report-section{{display:none}} .report-section.active{{display:block}} .section-header{{display:flex;align-items:center;gap:12px;margin:14px 0}}
.section-number{{display:grid;place-items:center;width:38px;height:38px;border-radius:11px;background:linear-gradient(135deg,var(--accent),var(--accent2));font-weight:800}}
h2{{font-size:21px;margin:0}} small{{color:var(--muted)}} .prose-card,.chart-card{{padding:22px;margin-bottom:16px}} p{{margin:0 0 13px}} p:last-child{{margin-bottom:0}}
.chart-card h3{{margin:0 0 12px;font-size:16px}} .chart-wrap{{height:330px}} .foot{{color:var(--muted);font-size:12px;margin-top:22px;padding:14px;border-top:1px solid var(--line)}}
@media(max-width:640px){{.wrap{{padding:16px 12px 52px}}.hero{{padding:22px}}.chart-wrap{{height:260px}}}}
</style>
</head>
<body>
<main class="wrap">
  <header class="hero">
    <h1>Thị trường Lãi suất &amp; Tiền tệ Việt Nam</h1>
    <div class="meta">
      <span class="badge">{_safe_text(_week_label(report))}</span>
      <span class="badge">Chốt dữ liệu: {cutoff}</span>
      <span class="badge verdict">{verdict}</span>
    </div>
  </header>
  <nav class="tabs">{"".join(tabs)}</nav>
  {"".join(section_html)}
  <footer class="foot">Nguồn: SBV, VBMA, VNBA, HNX và FRED. Nội dung tổng hợp số liệu, không phải khuyến nghị đầu tư.</footer>
</main>
<script>
const chartConfigs = {chart_json};
const rendered = new Set();
function renderCharts(sectionId) {{
  chartConfigs.filter(item => item.section === sectionId).forEach(item => {{
    if (rendered.has(item.id)) return;
    const canvas = document.getElementById(item.id);
    if (!canvas) return;
    new Chart(canvas, {{
      type: 'line',
      data: {{
        labels: item.labels,
        datasets: item.datasets.map(series => ({{
          label: series.label,
          data: series.data,
          borderColor: series.color,
          backgroundColor: series.color + '20',
          tension: .28,
          spanGaps: true,
          borderWidth: 2.5,
          pointRadius: 4
        }}))
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{legend: {{labels: {{color: '#93a4c3', usePointStyle: true}}}}}},
        scales: {{
          x: {{ticks: {{color: '#93a4c3'}}, grid: {{color: '#25324c55'}}}},
          y: {{ticks: {{color: '#93a4c3'}}, grid: {{color: '#25324c55'}}}}
        }}
      }}
    }});
    rendered.add(item.id);
  }});
}}
document.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', () => {{
  document.querySelectorAll('.tab').forEach(item => item.classList.remove('active'));
  document.querySelectorAll('.report-section').forEach(item => item.classList.remove('active'));
  tab.classList.add('active');
  const section = document.getElementById(tab.dataset.target);
  if (section) {{
    section.classList.add('active');
    requestAnimationFrame(() => renderCharts(section.id));
  }}
}}));
const initialSection = document.querySelector('.report-section.active');
if (initialSection) renderCharts(initialSection.id);
</script>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Render report.json to HTML")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_report(report), encoding="utf-8")
    print(f"Built data-driven report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
