"""Deterministic short-horizon analysis for the weekly VN rates report.

This module deliberately avoids an LLM opinion.  It fits a small linear trend
to the verified weekly observations and returns a point estimate plus a
prediction band.  The result is labelled as a model scenario so readers can
separate it from source facts.
"""
from __future__ import annotations

import math
from typing import Any


def _points(series: Any) -> list[tuple[float, float]]:
    if not isinstance(series, list):
        return []
    points = []
    for index, item in enumerate(series):
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            points.append((float(index), float(value)))
    return points


def _fit(points: list[tuple[float, float]]) -> dict[str, float | int | None]:
    n = len(points)
    if n == 0:
        return {"n": 0, "slope": None, "intercept": None, "r2": None, "residual": None}
    if n == 1:
        return {
            "n": 1,
            "slope": 0.0,
            "intercept": points[0][1],
            "r2": None,
            "residual": 0.0,
        }
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    ss_x = sum((x - mean_x) ** 2 for x, _ in points)
    if ss_x == 0:
        return {
            "n": n,
            "slope": 0.0,
            "intercept": mean_y,
            "r2": None,
            "residual": 0.0,
        }
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / ss_x
    intercept = mean_y - slope * mean_x
    fitted = [intercept + slope * x for x, _ in points]
    ss_res = sum((y - pred) ** 2 for (_, y), pred in zip(points, fitted))
    ss_tot = sum((y - mean_y) ** 2 for _, y in points)
    r2 = 1.0 - ss_res / ss_tot if ss_tot else 1.0
    residual = math.sqrt(ss_res / max(n - 2, 1))
    return {
        "n": n,
        "slope": slope,
        "intercept": intercept,
        "r2": max(0.0, min(1.0, r2)),
        "residual": residual,
    }


def _round(value: float, decimals: int) -> float:
    return round(float(value), decimals)


def _metric(
    key: str,
    label: str,
    unit: str,
    series: Any,
    horizons: tuple[int, ...] = (1, 2, 4),
) -> dict[str, Any]:
    points = _points(series)
    fit = _fit(points)
    n = int(fit["n"] or 0)
    if not points:
        return {
            "key": key,
            "label": label,
            "unit": unit,
            "status": "insufficient_data",
            "data_points": 0,
        }

    decimals = 0 if unit == "VND" else 2
    slope = float(fit["slope"] or 0.0)
    latest = points[-1][1]
    scale = max(abs(latest), 1.0)
    threshold = 0.0005 * scale if unit == "VND" else 0.03
    if abs(slope) <= threshold:
        signal = "đi ngang"
    elif slope > 0:
        signal = "tăng"
    else:
        signal = "giảm"

    r2 = fit["r2"]
    if n >= 4 and isinstance(r2, float) and r2 >= 0.5:
        confidence = "cao"
    elif n >= 3:
        confidence = "trung bình"
    else:
        confidence = "thấp"

    mean_x = sum(x for x, _ in points) / n
    ss_x = sum((x - mean_x) ** 2 for x, _ in points)
    residual = float(fit["residual"] or 0.0)
    forecasts: dict[str, dict[str, float]] = {}
    for horizon in horizons:
        x = points[-1][0] + horizon
        point = float(fit["intercept"] or 0.0) + slope * x
        if n > 1 and ss_x:
            se = residual * math.sqrt(1.0 + 1.0 / n + ((x - mean_x) ** 2) / ss_x)
        else:
            se = max(abs(slope), scale * 0.01)
        margin = max(1.96 * se, scale * 0.005)
        forecasts[f"{horizon}w"] = {
            "point": _round(point, decimals),
            "low": _round(point - margin, decimals),
            "high": _round(point + margin, decimals),
        }

    return {
        "key": key,
        "label": label,
        "unit": unit,
        "status": "ok",
        "data_points": n,
        "latest": _round(latest, decimals),
        "slope_per_week": _round(slope, decimals + 2),
        "signal": signal,
        "confidence": confidence,
        "r2": _round(float(r2), 2) if isinstance(r2, float) else None,
        "forecasts": forecasts,
    }


def build_forecast(report: dict[str, Any]) -> dict[str, Any]:
    """Build a transparent 1–4 week scenario from verified report series."""
    sections = report.get("sections", {})
    lnh = sections.get("lnh", {}).get("data_summary", {})
    lstp = sections.get("lstp", {}).get("data_summary", {})
    fx = sections.get("fx", {}).get("data_summary", {})
    metrics = [
        _metric("lnh_overnight", "LNH qua đêm", "%", lnh.get("on_4w")),
        _metric("lstp_10y", "LSTP 10 năm", "%", lstp.get("y10_4w")),
        _metric("usd_vnd", "USD/VND", "VND", fx.get("fx_mid_4w")),
    ]
    valid = {item["key"]: item for item in metrics if item.get("status") == "ok"}
    lnh_signal = valid.get("lnh_overnight", {}).get("signal")
    y10_signal = valid.get("lstp_10y", {}).get("signal")
    if lnh_signal == "tăng" and y10_signal == "tăng":
        scenario = "LNH và LSTP cùng có động lượng tăng"
    elif lnh_signal == "tăng" and y10_signal in {"giảm", "đi ngang"}:
        scenario = "LNH tăng; LSTP dài hạn chưa xác nhận"
    elif lnh_signal == "giảm" and y10_signal == "tăng":
        scenario = "LNH giảm trong khi LSTP dài hạn tăng"
    elif lnh_signal == "giảm" and y10_signal == "giảm":
        scenario = "LNH và LSTP cùng có động lượng giảm"
    else:
        scenario = "Các chuỗi đi ngang, phân kỳ hoặc chưa đủ dữ liệu"
    confidences = [
        item["confidence"] for item in metrics if item.get("status") == "ok"
    ]
    confidence = (
        "cao"
        if confidences and all(item == "cao" for item in confidences)
        else "trung bình"
        if confidences and any(item in {"cao", "trung bình"} for item in confidences)
        else "thấp"
    )
    return {
        "title": "Phân tích xu hướng 1–4 tuần",
        "method": "Hồi quy tuyến tính trên chuỗi tuần đã kiểm chứng; dải thấp/cao là khoảng dự báo thống kê 95%.",
        "scenario": scenario,
        "confidence": confidence,
        "horizons": [1, 2, 4],
        "metrics": metrics,
        "limitations": [
            "Ngoại suy không thay thế quyết định đầu tư.",
            "Kết quả nhạy với cú sốc chính sách, thanh khoản và tỷ giá ngoài cửa sổ quan sát.",
        ],
    }
