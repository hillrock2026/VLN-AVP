"""Deterministic, explainable route costs.

Cost direction: **lower is better**. Every component is non-negative except the
optional LTM adjustment, which may be negative (a historical preference bonus).
Weights are explicit and stable; there is no learned scoring.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .errors import PlanningValidationError
from .models import ParkingTopology, RouteCandidate, RouteCost

__all__ = ["CostWeights", "DEFAULT_COST_WEIGHTS", "compute_route_cost", "with_ltm_adjustment"]


@dataclass(frozen=True)
class CostWeights:
    """Interpretable weights for the base route cost."""

    length: float = 1.0
    turn: float = 2.0
    risk: float = 1.0

    def __post_init__(self) -> None:
        for name in ("length", "turn", "risk"):
            value = getattr(self, name)
            if type(value) is not int and type(value) is not float:
                raise PlanningValidationError(f"cost weight {name!r} must be a number")
            value = float(value)
            if not math.isfinite(value) or value < 0.0:
                raise PlanningValidationError(
                    f"cost weight {name!r} must be finite and >= 0"
                )
            object.__setattr__(self, name, value)


DEFAULT_COST_WEIGHTS = CostWeights()


def compute_route_cost(
    topology: ParkingTopology,
    candidate: RouteCandidate,
    weights: CostWeights = DEFAULT_COST_WEIGHTS,
    *,
    ltm_adjustment: float = 0.0,
) -> RouteCost:
    """Compute ``length + turn + risk + ltm``; all values are in cost units."""

    if not isinstance(weights, CostWeights):
        raise PlanningValidationError("weights must be a CostWeights")
    if type(ltm_adjustment) is not int and type(ltm_adjustment) is not float:
        raise PlanningValidationError("ltm_adjustment must be a number")
    ltm_adjustment = float(ltm_adjustment)
    if not math.isfinite(ltm_adjustment):
        raise PlanningValidationError("ltm_adjustment must be finite")

    turn_count = topology.route_turn_count(candidate.node_ids)
    risk_sum = sum(topology.edge(edge_id).risk for edge_id in candidate.edge_ids)
    length_component = candidate.length_m * weights.length
    turn_component = turn_count * weights.turn
    risk_component = risk_sum * weights.risk
    total = length_component + turn_component + risk_component + ltm_adjustment

    return RouteCost(
        length_component=length_component,
        turn_component=turn_component,
        risk_component=risk_component,
        ltm_component=ltm_adjustment,
        total=total,
        turn_count=turn_count,
        risk_sum=risk_sum,
    )


def with_ltm_adjustment(cost: RouteCost, adjustment: float) -> RouteCost:
    """Return a copy with the LTM component replaced."""

    if type(adjustment) is not int and type(adjustment) is not float:
        raise PlanningValidationError("adjustment must be a number")
    adjustment = float(adjustment)
    if not math.isfinite(adjustment):
        raise PlanningValidationError("adjustment must be finite")
    base_total = cost.total - cost.ltm_component
    return replace(
        cost,
        ltm_component=adjustment,
        total=base_total + adjustment,
    )
