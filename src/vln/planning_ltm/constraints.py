"""Independent hard-constraint checks for candidate routes.

Every violation is retained. Infeasible candidates are not removed from the
result; they carry stable codes and human-readable messages. LTM is never
consulted here, so no historical preference can clear a violation.

Not implemented (deliberately out of scope): vehicle kinematics, body/collision
footprints, dynamic obstacles, and time-dependent traffic.
"""

from __future__ import annotations

from .errors import TopologyValidationError
from .models import (
    ConstraintViolation,
    ParkingScene,
    RouteCandidate,
    ViolationCode,
)

__all__ = ["check_hard_constraints"]

_LENGTH_TOLERANCE_M = 1e-6


def check_hard_constraints(
    scene: ParkingScene, candidate: RouteCandidate
) -> tuple[ConstraintViolation, ...]:
    """Return every hard-constraint violation for one candidate."""

    topology = scene.topology
    violations: list[ConstraintViolation] = []

    if candidate.target_id != scene.target_id:
        violations.append(
            ConstraintViolation(
                ViolationCode.TARGET_MISMATCH,
                f"candidate targets {candidate.target_id!r}, "
                f"task targets {scene.target_id!r}",
            )
        )
    if candidate.start_node_id != scene.start_node_id:
        violations.append(
            ConstraintViolation(
                ViolationCode.START_MISMATCH,
                f"candidate starts at {candidate.start_node_id!r}, "
                f"scene starts at {scene.start_node_id!r}",
            )
        )
    if candidate.end_node_id != scene.target_node_id:
        violations.append(
            ConstraintViolation(
                ViolationCode.TARGET_NODE_MISMATCH,
                f"candidate ends at {candidate.end_node_id!r}, "
                f"target node is {scene.target_node_id!r}",
            )
        )

    known_nodes: set[str] = set()
    for node_id in candidate.node_ids:
        try:
            topology.node(node_id)
        except TopologyValidationError:
            violations.append(
                ConstraintViolation(
                    ViolationCode.UNKNOWN_NODE,
                    f"node {node_id!r} does not exist in the topology",
                )
            )
        else:
            known_nodes.add(node_id)

    fully_connected = True
    for index, (first, second) in enumerate(
        zip(candidate.node_ids, candidate.node_ids[1:])
    ):
        edge = topology.edge_between(first, second)
        if edge is None:
            fully_connected = False
            violations.append(
                ConstraintViolation(
                    ViolationCode.DISCONNECTED_ROUTE,
                    f"no topology edge connects {first!r} and {second!r}",
                )
            )
            continue
        if candidate.edge_ids[index] != edge.edge_id:
            violations.append(
                ConstraintViolation(
                    ViolationCode.EDGE_SEQUENCE_MISMATCH,
                    f"transition {first!r} -> {second!r} uses edge "
                    f"{edge.edge_id!r}, candidate declares "
                    f"{candidate.edge_ids[index]!r}",
                )
            )

    for node_id in candidate.node_ids:
        if node_id in scene.blocked_node_ids:
            violations.append(
                ConstraintViolation(
                    ViolationCode.BLOCKED_NODE,
                    f"route passes through blocked node {node_id!r}",
                )
            )
    for edge_id in candidate.edge_ids:
        if edge_id in scene.blocked_edge_ids:
            violations.append(
                ConstraintViolation(
                    ViolationCode.BLOCKED_EDGE,
                    f"route uses blocked edge {edge_id!r}",
                )
            )

    if scene.allowed_bounds is not None:
        for node_id in candidate.node_ids:
            if node_id not in known_nodes:
                continue
            node = topology.node(node_id)
            if not scene.allowed_bounds.contains(node.x, node.y):
                violations.append(
                    ConstraintViolation(
                        ViolationCode.OUTSIDE_ALLOWED_AREA,
                        f"node {node_id!r} at ({node.x}, {node.y}) is outside the "
                        "declared allowed area",
                    )
                )

    computed_length: float | None = None
    if fully_connected:
        computed_length = topology.route_length(candidate.node_ids)
        if abs(computed_length - candidate.length_m) > _LENGTH_TOLERANCE_M:
            violations.append(
                ConstraintViolation(
                    ViolationCode.LENGTH_MISMATCH,
                    f"declared length {candidate.length_m:.6f} m does not match "
                    f"topology length {computed_length:.6f} m",
                )
            )

    if scene.max_length_m is not None:
        measured = computed_length if computed_length is not None else candidate.length_m
        if measured > scene.max_length_m + _LENGTH_TOLERANCE_M:
            violations.append(
                ConstraintViolation(
                    ViolationCode.LENGTH_LIMIT,
                    f"route length {measured:.3f} m exceeds the scene limit "
                    f"{scene.max_length_m:.3f} m",
                )
            )

    if scene.max_turn_count is not None and known_nodes == set(candidate.node_ids):
        turn_count = topology.route_turn_count(candidate.node_ids)
        if turn_count > scene.max_turn_count:
            violations.append(
                ConstraintViolation(
                    ViolationCode.TURN_LIMIT,
                    f"route has {turn_count} turn(s), exceeding the scene limit "
                    f"{scene.max_turn_count}",
                )
            )

    return tuple(violations)
