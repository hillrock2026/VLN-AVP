"""Target-bay approach area and independent approach verdict.

CAP-07B stops near the bound bay, not inside it. The approach area is a graph
node in front of the slot, derived from the same measured parking graph used by
the existing controller:

* ``park_slot`` (bay03) -> ``park_entry``;
* ``bay11_slot`` (bay11) -> ``bay11_turn``.

This is scene geometry, not a model output and not a route/turn preset. The
navigation runtime still lets Taichu choose each route edge; the approach node
only defines where the run is allowed to stop.

The verdict here is independent of the model, the Kernel status and the
``goal_reached`` flag: it checks the real stopped pose against the approach
node, the bound scene identity, the collision counter and the final Kernel
execution status. It never claims a parking completion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from vln.carla.goal import GoalEvaluation
from vln.carla.parking_verdict import PARKING_SLOT_NODE_ID
from vln.carla.underground_carpark_parking import (
    BAY11_SLOT_NODE_ID,
    BAY11_TURN_NODE_ID,
    UNDERGROUND_CARPARK_PARKING_ENTRY_NODE,
)

__all__ = [
    "APPROACH_NODE_BY_SLOT",
    "ApproachVerdict",
    "approach_node_for_slot",
    "evaluate_target_approach",
]


#: The safe aisle point in front of each bound parking slot. The values are
#: the parking graph's own entry/turn nodes; no new waypoint is invented.
APPROACH_NODE_BY_SLOT = {
    PARKING_SLOT_NODE_ID: UNDERGROUND_CARPARK_PARKING_ENTRY_NODE,
    BAY11_SLOT_NODE_ID: BAY11_TURN_NODE_ID,
}


def approach_node_for_slot(slot_node_id: str) -> str:
    if type(slot_node_id) is not str or slot_node_id.strip() == "":
        raise ValueError("slot_node_id must be a non-blank str")
    try:
        return APPROACH_NODE_BY_SLOT[slot_node_id]
    except KeyError:
        raise KeyError(
            f"no approach node is defined for slot {slot_node_id!r}"
        ) from None


@dataclass(frozen=True)
class ApproachVerdict:
    """Independent check that the real stop is at the bound target's approach."""

    ok: bool
    task_id: str
    target_id: str
    bay_id: str
    slot_node_id: str
    approach_node_id: str
    goal: Optional[Mapping[str, object]] = None
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.task_id) is not str or self.task_id.strip() == "":
            raise ValueError("task_id must be a non-blank str")
        if type(self.target_id) is not str or self.target_id.strip() == "":
            raise ValueError("target_id must be a non-blank str")
        if type(self.bay_id) is not str or self.bay_id.strip() == "":
            raise ValueError("bay_id must be a non-blank str")
        if type(self.slot_node_id) is not str or self.slot_node_id.strip() == "":
            raise ValueError("slot_node_id must be a non-blank str")
        if type(self.approach_node_id) is not str or not self.approach_node_id:
            raise ValueError("approach_node_id must be a non-blank str")
        if self.ok and self.reasons:
            raise ValueError("an accepted approach cannot carry failure reasons")
        if not self.ok and not self.reasons:
            raise ValueError("a rejected approach must carry at least one reason")

    def to_metadata(self) -> dict:
        return {
            "ok": self.ok,
            "task_id": self.task_id,
            "target_id": self.target_id,
            "bay_id": self.bay_id,
            "slot_node_id": self.slot_node_id,
            "approach_node_id": self.approach_node_id,
            "goal": dict(self.goal) if self.goal is not None else None,
            "reasons": list(self.reasons),
        }


def evaluate_target_approach(
    *,
    task_id: str,
    binding: object,
    approach_node_id: str,
    goal_evaluation: GoalEvaluation,
    target_id: Optional[str] = None,
    collision_count: int = 0,
    kernel_execution_status: Optional[str] = None,
) -> ApproachVerdict:
    """Check the real final stop against the bound bay's approach area."""

    if type(task_id) is not str or task_id.strip() == "":
        raise ValueError("task_id must be a non-blank str")
    status = getattr(binding, "status", None)
    bay_id = getattr(binding, "bay_id", None)
    slot_node_id = getattr(binding, "slot_node_id", None)
    if status != "bound":
        raise ValueError(f"binding status {status!r} is not executable")
    if type(bay_id) is not str or not bay_id:
        raise ValueError("bound binding must carry bay_id")
    if type(slot_node_id) is not str or not slot_node_id:
        raise ValueError("bound binding must carry slot_node_id")
    if target_id is None:
        target_id = bay_id
    if type(target_id) is not str or target_id.strip() == "":
        raise ValueError("target_id must be a non-blank str")
    if approach_node_id != approach_node_for_slot(slot_node_id):
        raise ValueError(
            f"approach node {approach_node_id!r} does not match the bound slot "
            f"{slot_node_id!r}"
        )
    if not isinstance(goal_evaluation, GoalEvaluation):
        raise TypeError("goal_evaluation must be a GoalEvaluation")
    if type(collision_count) is not int or collision_count < 0:
        raise ValueError("collision_count must be a non-negative int")
    if kernel_execution_status is not None and type(kernel_execution_status) is not str:
        raise ValueError("kernel_execution_status must be a str or None")

    reasons: list[str] = []
    if target_id != bay_id:
        reasons.append("target_id_changed_without_evidence")
    if goal_evaluation.node_id != approach_node_id:
        reasons.append("goal_node_is_not_the_approach_node")
    if not goal_evaluation.ok:
        reasons.extend(f"approach_{reason}" for reason in goal_evaluation.reasons)
    if collision_count:
        reasons.append(f"collision_count={collision_count}")
    if kernel_execution_status is not None and kernel_execution_status != "completed":
        reasons.append(f"kernel_execution_status={kernel_execution_status}")

    return ApproachVerdict(
        ok=not reasons,
        task_id=task_id,
        target_id=target_id,
        bay_id=bay_id,
        slot_node_id=slot_node_id,
        approach_node_id=approach_node_id,
        goal=goal_evaluation.to_metadata(),
        reasons=tuple(dict.fromkeys(reasons)),
    )
