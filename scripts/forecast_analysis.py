"""Deterministic short-horizon analysis for the weekly VN rates report.

The model is deliberately conservative. It keeps observed facts separate from
conditional extrapolation, suppresses numeric forecasts when the latest move
conflicts with the fitted trend, and never treats an increase/decrease as
universally good or bad.
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


def _neutral_assessment(key: str, signal: str) -> str:
    if key == "lnh_overnight":
        if signal == "tăng":
            return (
                "Chi phí vốn qua đêm giữa các ngân hàng cao hơn tại kỳ quan sát; "
                "không tự động là tốt hoặc xấu cho toàn thị trường."
            )
        if signal == "giảm":
            return (
                "Chi phí vốn qua đêm giữa các ngân hàng thấp hơn tại kỳ quan sát; "
                "chưa đủ để kết luận về thanh khoản hay định hướng chính sách."
            )
        return (
            "Chi phí vốn qua đêm ít thay đổi ở kỳ gần nhất; trạng thái này không "
            "tự động là tốt hoặc xấu."
        )
    if key == "lstp_10y":
        if signal == "tăng":
            return (
                "Lợi suất chuẩn dài hạn cao hơn và giá trái phiếu thường chịu tác "
                "động ngược chiều; ảnh hưởng khác nhau với người vay và người nắm giữ."
            )
        if signal == "giảm":
            return (
                "Lợi suất chuẩn dài hạn thấp hơn và giá trái phiếu thường biến động "
                "ngược chiều; ảnh hưởng khác nhau với người vay và người nắm giữ."
            )
        return (
            "Lợi suất chuẩn dài hạn ít thay đổi ở kỳ gần nhất; chưa xác nhận một "
            "hướng mới."
        )
    if key == "usd_vnd":
        if signal == "tăng":
            return (
                "USD cao hơn so với VND trong cặp tỷ giá quan sát; tác động khác nhau "
                "giữa bên nhập khẩu, xuất khẩu, vay và nắm giữ ngoại tệ."
            )
        if signal == "giảm":
            return (
                "USD thấp hơn so với VND trong cặp tỷ giá quan sát; tác động khác nhau "
                "giữa bên nhập khẩu, xuất khẩu, vay và nắm giữ ngoại tệ."
            )
        return (
            "USD/VND ít thay đổi ở kỳ gần nhất; không đồng nghĩa rủi ro tỷ giá đã "
            "biến mất."
        )
    return "Tăng/giảm không tự động đồng nghĩa tốt/xấu; cần xét theo từng chủ thể."


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
            "forecast_status": "insufficient_data",
            "data_points": 0,
            "confidence": "thấp",
            "show_numeric_forecast": False,
            "neutral_assessment": "Không có đủ dữ liệu đã kiểm chứng để đánh giá.",
        }

    decimals = 0 if unit == "VND" else 2
    slope = float(fit["slope"] or 0.0)
    latest = points[-1][1]
    scale = max(abs(latest), 1.0)
    threshold = 0.0005 * scale if unit == "VND" else 0.03
    # Headline direction means the latest observed move. The regression slope
    # remains available separately as the fitted-window trend.
    observed_change = latest - points[-2][1] if n >= 2 else 0.0
    if n < 2:
        signal = "chưa đủ dữ liệu"
    elif abs(observed_change) <= threshold:
        signal = "đi ngang"
    elif observed_change > 0:
        signal = "tăng"
    else:
        signal = "giảm"

    if abs(slope) <= threshold:
        trend_signal = "đi ngang"
    elif slope > 0:
        trend_signal = "tăng"
    else:
        trend_signal = "giảm"

    r2 = fit["r2"]
    direction_consistent = n >= 2 and signal == trend_signal
    if n < 4:
        confidence = "thấp"
        forecast_status = "insufficient_data"
    elif not direction_consistent:
        confidence = "thấp"
        forecast_status = "direction_conflict"
    elif isinstance(r2, float) and r2 >= 0.75:
        confidence = "cao"
        forecast_status = "published"
    elif isinstance(r2, float) and r2 >= 0.5:
        confidence = "trung bình"
        forecast_status = "published"
    else:
        confidence = "thấp"
        forecast_status = "low_confidence"

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
        "previous": _round(points[-2][1], decimals) if n >= 2 else None,
        "observed_change": _round(observed_change, decimals + 2) if n >= 2 else None,
        "slope_per_week": _round(slope, decimals + 2),
        "signal": signal,
        "trend_signal": trend_signal,
        "direction_consistent": direction_consistent,
        "confidence": confidence,
        "forecast_status": forecast_status,
        "show_numeric_forecast": forecast_status == "published",
        "neutral_assessment": _neutral_assessment(key, signal),
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
        _metric(
            "lnh_overnight",
            "LNH ON đóng cửa thứ Sáu (VBMA)",
            "%",
            lnh.get("on_4w"),
        ),
        _metric("lstp_10y", "LSTP 10 năm", "%", lstp.get("y10_4w")),
        _metric("usd_vnd", "USD/VND", "VND", fx.get("fx_mid_4w")),
    ]
    valid = {item["key"]: item for item in metrics if item.get("status") == "ok"}

    observed_parts = [
        f"{item['label']}: {item['signal']}"
        for item in metrics
        if item.get("status") == "ok"
    ]
    observed_state = (
        "Kỳ gần nhất — " + "; ".join(observed_parts)
        if observed_parts
        else "Kỳ gần nhất — chưa đủ dữ liệu đã kiểm chứng"
    )

    published = [
        item for item in metrics if item.get("show_numeric_forecast") is True
    ]
    if published:
        projected = "; ".join(
            f"{item['label']} {item['trend_signal']}" for item in published
        )
        base_case = (
            "Nếu quan hệ trong cửa sổ 4 tuần tiếp diễn, mô hình nghiêng về "
            f"{projected}. Đây là kịch bản có điều kiện, không phải kết luận."
        )
    else:
        base_case = (
            "Chưa công bố kịch bản số vì dữ liệu, độ phù hợp hoặc hướng biến động "
            "chưa vượt ngưỡng nhất quán."
        )

    confidence = (
        "cao"
        if len(published) == len(metrics)
        and all(item.get("confidence") == "cao" for item in published)
        else "trung bình"
        if len(published) >= 2
        else "thấp"
    )
    hidden = [
        item["label"]
        for item in metrics
        if item.get("show_numeric_forecast") is not True
    ]
    confidence_basis = (
        f"{len(published)}/{len(metrics)} chuỗi đủ điều kiện công bố dải số"
        + (f"; đang ẩn: {', '.join(hidden)}" if hidden else "")
    )

    confirmation_conditions = [
        (
            f"{item['label']}: kỳ kế tiếp tiếp tục {item['trend_signal']} và dữ liệu "
            "nguồn vẫn vượt kiểm chứng."
        )
        for item in published
    ]
    if not confirmation_conditions:
        confirmation_conditions = [
            "Cần ít nhất 4 kỳ đã kiểm chứng, hướng kỳ gần nhất trùng xu hướng cửa sổ và R² ≥ 0,50."
        ]
    invalidation_conditions = [
        "Kỳ mới đảo hướng so với xu hướng cửa sổ hoặc nằm ngoài dải mô hình.",
        "Nguồn sửa số, thiếu kỳ, hoặc phát hiện trộn định nghĩa đóng cửa và bình quân tuần.",
    ]
    return {
        "title": "Phân tích xu hướng 1–4 tuần",
        "method": (
            "Hồi quy tuyến tính trên 4 kỳ đã kiểm chứng. Dải số chỉ hiển thị khi "
            "hướng kỳ gần nhất trùng xu hướng cửa sổ và R² ≥ 0,50; dải thấp/cao là "
            "khoảng dự báo thống kê 95%."
        ),
        "scenario": observed_state,
        "observed_state": observed_state,
        "base_case": base_case,
        "confidence": confidence,
        "confidence_basis": confidence_basis,
        "horizons": [1, 2, 4],
        "metrics": metrics,
        "confirmation_conditions": confirmation_conditions,
        "invalidation_conditions": invalidation_conditions,
        "balance_notes": [
            "Tăng/giảm không tự động đồng nghĩa tốt/xấu; tác động khác nhau theo từng chủ thể.",
            "Độ tin cậy là mức kiểm chứng nội bộ của mô hình, không phải xác suất xảy ra.",
        ],
        "uncertainty_note": (
            "Dự báo chỉ là kịch bản có điều kiện. Khi điều kiện chưa đạt, hệ thống "
            "thà không đưa số hơn là lấp chỗ trống bằng ước đoán."
        ),
        "limitations": [
            "Ngoại suy không thay thế quyết định đầu tư.",
            "Kết quả nhạy với cú sốc chính sách, thanh khoản và tỷ giá ngoài cửa sổ quan sát.",
        ],
    }
