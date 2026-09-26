"""Curve engine: piecewise-linear payout curves (industry-standard rate tables).

v5.0: interpolation points and the payout cap must be INTEGERS. A decimal or
otherwise malformed value is rejected with an explicit "请以整数格式输入" message so
an admin can never publish a fractional breakpoint by accident.
"""


class IntegerRequired(ValueError):
    """Raised when a curve point or the cap is not a plain integer."""


INT_HINT = "请以整数格式输入"


def _as_int(raw: str, label: str) -> int:
    token = str(raw).strip().replace("%", "").replace("，", "")
    if token == "":
        raise IntegerRequired(f"{label}：{INT_HINT}")
    try:
        return int(token, 10)
    except ValueError:
        # rejects "80.5", "1e2", "80,0" spellings and anything else non-integral
        raise IntegerRequired(f"{label}：{INT_HINT}") from None


def parse_points(text: str) -> list[list[int]]:
    """Parse '0:0, 80:50, 100:100' into sorted [[attainment, payout], ...].

    Every value must be an integer; anything else raises IntegerRequired."""
    points: list[list[int]] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise IntegerRequired(f"插值点：{INT_HINT}（格式 达成率:支付率）")
        x, y = part.split(":", 1)
        points.append([_as_int(x, "达成率"), _as_int(y, "支付率")])
    points.sort(key=lambda p: p[0])
    if len(points) < 2:
        raise ValueError("Curve 至少需要两个点，格式如 0:0,100:100")
    return points


def parse_cap(raw) -> int | None:
    """Cap payout rate: blank/None = no cap, otherwise an integer percentage."""
    if raw is None or str(raw).strip() == "":
        return None
    return _as_int(raw, "封顶支付率")


def interpolate(points: list[list[float]], attainment_pct: float) -> float:
    """Linear interpolation, clamped at both ends (no extrapolation)."""
    if attainment_pct <= points[0][0]:
        return points[0][1]
    if attainment_pct >= points[-1][0]:
        return points[-1][1]
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        if x1 <= attainment_pct <= x2:
            if x2 == x1:
                return y2
            return y1 + (y2 - y1) * (attainment_pct - x1) / (x2 - x1)
    return points[-1][1]


def payout_rate(points: list[list[float]], attainment_pct: float, cap_pct: float | None = None) -> float:
    rate = interpolate(points, attainment_pct)
    if cap_pct is not None:
        rate = min(rate, cap_pct)
    return round(rate, 4)
