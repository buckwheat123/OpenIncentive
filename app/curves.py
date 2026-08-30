"""Curve engine: piecewise-linear payout curves (industry-standard rate tables)."""


def parse_points(text: str) -> list[list[float]]:
    """Parse '0:0, 80:50, 100:100' into sorted [[attainment, payout], ...]."""
    points: list[list[float]] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        x, y = part.split(":")
        points.append([float(x), float(y)])
    points.sort(key=lambda p: p[0])
    if len(points) < 2:
        raise ValueError("Curve 至少需要两个点，格式如 0:0,100:100")
    return points


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
