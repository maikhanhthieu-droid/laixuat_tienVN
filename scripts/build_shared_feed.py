#!/usr/bin/env python3
"""Export verified rate facts for other repositories.

The feed intentionally excludes forecasts, prose and AI output.  Consumers
must treat each fact independently and check ``status``/``as_of`` before use.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "vn-rates.facts.v1"


def _latest(series: Any) -> float | int | None:
    if not isinstance(series, list):
        return None
    for item in reversed(series):
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return value
    return None


def _fact(
    value: float | int | None,
    *,
    unit: str,
    definition: str,
    source: str,
    source_artifact: str,
    as_of: str | None,
) -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "definition": definition,
        "as_of": as_of,
        "source": source,
        "source_artifact": source_artifact,
        "status": "ok" if value is not None and as_of else "missing",
    }


def build_feed(report: dict[str, Any]) -> dict[str, Any]:
    period = report.get("period", {})
    as_of = period.get("data_cutoff")
    weeks = period.get("weeks_covered")
    latest_week = weeks[-1] if isinstance(weeks, list) and weeks else None
    short_week = latest_week.split("-")[-1] if isinstance(latest_week, str) else "unknown"
    sections = report.get("sections", {})
    lnh = sections.get("lnh", {}).get("data_summary", {})
    lstp = sections.get("lstp", {}).get("data_summary", {})
    fx = sections.get("fx", {}).get("data_summary", {})

    facts = {
        "interbank_overnight_close": _fact(
            _latest(lnh.get("on_4w")),
            unit="percent",
            definition="VBMA Friday close",
            source="VBMA",
            source_artifact=f"vbma_{short_week}.txt",
            as_of=as_of,
        ),
        "interbank_overnight_weekly_average": _fact(
            _latest(lnh.get("on_avg_4w")),
            unit="percent",
            definition="SBV weekly average",
            source="SBV",
            source_artifact=f"sbv_{latest_week}.txt" if latest_week else "unknown",
            as_of=as_of,
        ),
        "government_bond_10y": _fact(
            _latest(lstp.get("y10_4w")),
            unit="percent",
            definition="VBMA secondary-market 10-year yield",
            source="VBMA",
            source_artifact=f"vbma_{short_week}.txt",
            as_of=as_of,
        ),
        "usd_vnd_commercial_mid": _fact(
            _latest(fx.get("fx_mid_4w")),
            unit="VND_per_USD",
            definition="Midpoint of SBV-reported commercial-bank range",
            source="SBV",
            source_artifact=f"sbv_{latest_week}.txt" if latest_week else "unknown",
            as_of=as_of,
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "producer": "maikhanhthieu-droid/laixuat_tienVN",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of,
        "status": "ok" if any(item["status"] == "ok" for item in facts.values()) else "missing",
        "facts": facts,
        "quality": {
            "facts_only": True,
            "forecasts_included": False,
            "ai_output_included": False,
            "verification_required_before_export": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    feed = build_feed(report)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Built shared facts feed: {out}")


if __name__ == "__main__":
    main()
