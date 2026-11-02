"""Pure checks linking one closed-loop round to the next.

The runnable script uses these helpers instead of ad-hoc comparisons, so the
two claims that make a multi-round run meaningful are testable offline:

* the state used by round N+1 is the state read after round N's real stop;
* the image used by round N+1 is a different, later frame.

Nothing here talks to CARLA or the model. A passing linkage test is evidence
about the runner's bookkeeping only; it is not evidence that a vehicle moved.
"""

from __future__ import annotations

from .observation import SUCCESS
from .route_arbitration import RouteArbitrationStatus

__all__ = [
    "states_match",
    "build_round_linkage",
    "may_drive",
    "TaskStatus",
    "resolve_task_status",
]


class TaskStatus:
    """Final outcomes of a multi-round navigation task."""

    GOAL_REACHED = "goal_reached"
    RUNNING = "running"
    DECISION_REJECTED = "decision_rejected"
    SAFETY_STOPPED = "safety_stopped"
    TIMEOUT = "timeout"
    MAX_ROUNDS = "max_rounds"
    EXECUTION_ERROR = "execution_error"
    PARKING_NOT_CONFIRMED = "parking_not_confirmed"
    TARGET_APPROACH_NOT_CONFIRMED = "target_approach_not_confirmed"
    ALL = frozenset(
        {
            GOAL_REACHED,
            RUNNING,
            DECISION_REJECTED,
            SAFETY_STOPPED,
            TIMEOUT,
            MAX_ROUNDS,
            EXECUTION_ERROR,
            PARKING_NOT_CONFIRMED,
            TARGET_APPROACH_NOT_CONFIRMED,
        }
    )


def resolve_task_status(
    *,
    goal_reached: bool,
    decision_rejected: bool = False,
    safety_stopped: bool = False,
    timed_out: bool = False,
    max_rounds: bool = False,
    execution_error: bool = False,
) -> str:
    """Pick one final task status with a fixed, testable priority.

    A real goal arrival always wins; otherwise an execution error, a rejected
    decision, a safety stop, a timeout and the round limit are reported in that
    order. ``running`` is returned only when no terminal condition was seen.
    """

    if goal_reached:
        return TaskStatus.GOAL_REACHED
    if execution_error:
        return TaskStatus.EXECUTION_ERROR
    if decision_rejected:
        return TaskStatus.DECISION_REJECTED
    if safety_stopped:
        return TaskStatus.SAFETY_STOPPED
    if timed_out:
        return TaskStatus.TIMEOUT
    if max_rounds:
        return TaskStatus.MAX_ROUNDS
    return TaskStatus.RUNNING


def states_match(
    previous: dict | None, current: dict | None, tolerance_m: float = 0.1
) -> bool:
    """Are two CARLA state records the same stopped pose within tolerance?"""

    if previous is None or current is None:
        return False
    try:
        return (
            abs(float(previous["x"]) - float(current["x"])) <= tolerance_m
            and abs(float(previous["y"]) - float(current["y"])) <= tolerance_m
            and abs(float(previous["z"]) - float(current["z"])) <= tolerance_m
        )
    except (KeyError, TypeError, ValueError):
        return False


def build_round_linkage(
    *,
    round_index: int,
    previous_post_state: dict | None,
    previous_frame_sha256: str | None,
    current_state: dict,
    current_frame_sha256: str,
    expected_node_id: str | None,
) -> dict:
    """Return the evidence fields that tie this round to the previous one."""

    if type(round_index) is not int or round_index < 1:
        raise ValueError("round_index must be a positive int")
    return {
        "previous_round": None if round_index == 1 else round_index - 1,
        "previous_frame_sha256": previous_frame_sha256,
        "new_frame_sha256": current_frame_sha256,
        "frame_changed": (
            previous_frame_sha256 is not None
            and previous_frame_sha256 != current_frame_sha256
        ),
        "pre_state_matches_previous_post_state": (
            None
            if round_index == 1
            else states_match(previous_post_state, current_state)
        ),
        "expected_node_id": expected_node_id,
    }


def may_drive(*, decision_status: str, arbitration_status: str) -> bool:
    """The single gate between the decision chain and the vehicle controller."""

    return (
        decision_status == SUCCESS
        and arbitration_status == RouteArbitrationStatus.SELECTED
    )
