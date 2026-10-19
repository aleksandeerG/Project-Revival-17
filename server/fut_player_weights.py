# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations

import math


DEFAULT_POLICY = {
    "overallShare": 0.25,
    "headlineStatsShare": 0.75,
    "eliteBaseline": 75.0,
    "eliteDoublingInterval": 10.0,
    "inversePowerExponent": 2.0,
    "maxOddsRatio": 500.0,
    "poolKindMultipliers": {"base": 1.0, "special": 1.0},
    "positionWeights": {
        "CB": [23, 1, 7, 5, 36, 28],
        "FB_WB": [32, 3, 15, 16, 20, 14],
        "CDM": [17, 7, 19, 12, 25, 20],
        "CM": [17, 13, 25, 21, 10, 14],
        "CAM": [22, 21, 23, 26, 2, 6],
        "WIDE_ATTACKER": [35, 19, 14, 25, 1, 6],
        "ST_CF": [29, 30, 8, 22, 0, 11],
        "GK": [24, 19, 9, 24, 10, 14],
    },
}


def position_group(position: str) -> str:
    position = str(position or "CM").upper()
    if position == "GK":
        return "GK"
    if position == "CB":
        return "CB"
    if position in {"LB", "LWB", "RB", "RWB"}:
        return "FB_WB"
    if position == "CDM":
        return "CDM"
    if position == "CM":
        return "CM"
    if position == "CAM":
        return "CAM"
    if position in {"LM", "LW", "LF", "RM", "RW", "RF"}:
        return "WIDE_ATTACKER"
    if position in {"CF", "ST"}:
        return "ST_CF"
    return "CM"


def _number(policy: dict, name: str) -> float:
    try:
        value = float(policy.get(name, DEFAULT_POLICY[name]))
    except (TypeError, ValueError):
        value = float(DEFAULT_POLICY[name])
    return value if math.isfinite(value) else float(DEFAULT_POLICY[name])


def _position_weights(position: str, policy: dict) -> list[float]:
    group = position_group(position)
    configured = policy.get("positionWeights", {})
    values = configured.get(group, DEFAULT_POLICY["positionWeights"][group]) \
        if isinstance(configured, dict) else \
        DEFAULT_POLICY["positionWeights"][group]
    try:
        weights = [max(0.0, float(value)) for value in values]
    except (TypeError, ValueError):
        weights = []
    if len(weights) != 6 or not math.isfinite(sum(weights)) or sum(weights) <= 0:
        weights = [float(value) for value in
                   DEFAULT_POLICY["positionWeights"][group]]
    total = sum(weights)
    return [value / total for value in weights]


def elite_value(value: float, policy: dict | None = None) -> float:
    selected = policy or {}
    baseline = _number(selected, "eliteBaseline")
    interval = max(0.01, _number(selected, "eliteDoublingInterval"))
    value = max(0.0, min(99.0, float(value)))
    return 2.0 ** ((value - baseline) / interval)


def card_power(rating: int, position: str, headline_stats: list,
               policy: dict | None = None) -> float:
    selected = policy or {}
    try:
        stats = [max(0, min(99, int(value))) for value in headline_stats]
    except (TypeError, ValueError):
        stats = []
    if len(stats) != 6:
        stats = [max(0, min(99, int(rating)))] * 6

    overall_share = max(0.0, _number(selected, "overallShare"))
    stats_share = max(0.0, _number(selected, "headlineStatsShare"))
    share_total = overall_share + stats_share
    if share_total <= 0:
        overall_share, stats_share, share_total = 0.25, 0.75, 1.0
    overall_share /= share_total
    stats_share /= share_total

    stat_power = sum(weight * elite_value(value, selected)
                     for weight, value in zip(
                         _position_weights(position, selected), stats))
    return (overall_share * elite_value(rating, selected) +
            stats_share * stat_power)


def raw_draw_weight(rating: int, position: str, headline_stats: list,
                    policy: dict | None = None) -> float:
    selected = policy or {}
    exponent = max(0.0, _number(selected, "inversePowerExponent"))
    return card_power(rating, position, headline_stats, selected) ** -exponent


def pool_kind_multiplier(kind: str, policy: dict | None = None) -> float:
    selected = policy or {}
    configured = selected.get("poolKindMultipliers", {})
    defaults = DEFAULT_POLICY["poolKindMultipliers"]
    fallback = float(defaults.get(str(kind), 1.0))
    try:
        value = float(configured.get(str(kind), fallback)) \
            if isinstance(configured, dict) else fallback
    except (TypeError, ValueError):
        value = fallback
    return value if math.isfinite(value) and value > 0 else fallback


def pool_draw_weight(kind: str, rating: int, position: str,
                     headline_stats: list,
                     policy: dict | None = None) -> float:
    return (raw_draw_weight(rating, position, headline_stats, policy) *
            pool_kind_multiplier(kind, policy))


def bounded_draw_weights(raw_weights: list[float],
                         policy: dict | None = None) -> list[float]:
    if not raw_weights:
        return []
    selected = policy or {}
    ratio = max(1.0, _number(selected, "maxOddsRatio"))
    clean = [value if math.isfinite(value) and value > 0 else 1.0
             for value in raw_weights]
    floor = max(clean) / ratio
    return [max(value, floor) for value in clean]
