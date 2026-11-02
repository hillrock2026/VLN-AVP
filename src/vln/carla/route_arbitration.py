"""Verified visual direction + real pose + waypoint graph -> one feasible edge.

This is the missing layer between 01C and 01B. 01C proves the model can emit a
verified ``RIGHT``; 01B can plan and drive a graph route. Neither can decide,
on its own, that "RIGHT in the image" means "this particular edge from where
the car actually is". This module makes that decision explicit and refuses
when it cannot be made safely.

Contract, in order:

1. The input directive must be a verified
   :class:`~vln.nav.visual_decision.NavigationDirective`, its direction must be
   in the closed vocabulary, and the accompanying ``AgentIntent`` must agree
   with the real pose and the declared direction->heading convention. A stale
   or fabricated intent is refused; ``target.heading`` is never used to steer.
2. The real pose is matched to exactly one graph node within a small radius.
   Far from the graph, or equidistant between nodes, is ``pose_uncertain``.
3. Every outgoing edge is classified by its **world bearing relative to the
   vehicle's current heading**: ``STRAIGHT`` inside a symmetric deadband,
   ``LEFT``/``RIGHT`` outside it, ``BEHIND`` beyond the turn limit. Screen
   left/right and coordinate signs are never used.
4. Only reachable edges whose class equals the model's direction are
   candidates. If several match, the smallest absolute turn wins; a near-tie
   is ``ambiguous`` and refused, because there is no safe deterministic reason
   to prefer one.
5. The result is a typed value. Only ``selected`` carries a route the caller
   may drive; every other status is a safe refusal.

The layer has no CARLA, model, host or execution import. It returns data; it
never applies a control.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from vln.intent.agent_intent import AgentIntent, normalize_heading
from vln.nav.adapter import DIRECTION_HEADING_DELTA, VehiclePose
from vln.nav.visual_decision import NavigationDirective

from .route_control import classify_relative_turn, wrap_angle
from .waypoints import RouteGraph

__all__ = [
    "RouteArbitrationStatus",
    "RouteCandidatesStatus",
    "RouteCandidate",
    "RouteArbitrationResult",
    "RouteCandidatesResult",
    "arbitrate_route",
    "route_candidates",
    "forward_reachable_candidates",
    "execution_route",
    "APPROVED_MODEL_DIRECTIONS",
]

APPROVED_MODEL_DIRECTIONS = ("LEFT", "RIGHT", "STRAIGHT")


class RouteArbitrationStatus:
    """Terminal outcomes; only ``SELECTED`` authorises a driving segment."""

    SELECTED = "selected"
    NO_COMPATIBLE_ROUTE = "no_compatible_route"
    AMBIGUOUS = "ambiguous"
    UNREACHABLE_TARGET = "unreachable_target"
    POSE_UNCERTAIN = "pose_uncertain"
    INVALID_INTENT = "invalid_intent"
    SAFETY_UNSATISFIED = "safety_unsatisfied"
    ALL = frozenset(
        {
            SELECTED,
            NO_COMPATIBLE_ROUTE,
            AMBIGUOUS,
            UNREACHABLE_TARGET,
            POSE_UNCERTAIN,
            INVALID_INTENT,
            SAFETY_UNSATISFIED,
        }
    )
    REFUSED = frozenset(ALL - {SELECTED})


@dataclass(frozen=True)
class RouteCandidate:
    """One outgoing edge, its relative turn and its route to the goal."""

    from_node_id: str
    to_node_id: str
    distance_m: float
    bearing_rad: float
    relative_turn_rad: float
    turn_class: str
    reachable: bool
    matches_direction: bool
    route_node_ids: tuple[str, ...]
    rejection_reason: str | None
    blocked: bool = False

    def to_metadata(self) -> dict:
        return {
            "from_node_id": self.from_node_id,
            "to_node_id": self.to_node_id,
            "distance_m": round(self.distance_m, 3),
            "bearing_rad": round(self.bearing_rad, 6),
            "bearing_deg": round(math.degrees(self.bearing_rad), 3),
            "relative_turn_rad": round(self.relative_turn_rad, 6),
            "relative_turn_deg": round(math.degrees(self.relative_turn_rad), 3),
            "turn_class": self.turn_class,
            "reachable": self.reachable,
            "matches_direction": self.matches_direction,
            "blocked": self.blocked,
            "route_node_ids": list(self.route_node_ids),
            "rejection_reason": self.rejection_reason,
        }


class RouteCandidatesStatus:
    """Outcome of a direction-free candidate listing.

    Only ``OK`` carries candidates. The other statuses mirror the two
    pre-decision refusals of :func:`arbitrate_route`; they never authorise
    driving.
    """

    OK = "ok"
    POSE_UNCERTAIN = "pose_uncertain"
    UNREACHABLE_TARGET = "unreachable_target"


@dataclass(frozen=True)
class RouteCandidatesResult:
    """Real outgoing edges from the matched node before a model direction.

    This is the same computation :func:`arbitrate_route` performs, exposed
    without a direction so a prompt can describe the feasible branches the
    model must choose between. It selects nothing and authorises nothing.
    """

    status: str
    reason: str
    pose: VehiclePose | None
    matched_node_id: str | None
    matched_node_distance_m: float | None
    candidates: tuple[RouteCandidate, ...]
    route_node_ids: tuple[str, ...]
    route_points: tuple[tuple[float, float], ...]

    @property
    def ok(self) -> bool:
        return self.status == RouteCandidatesStatus.OK

    def to_metadata(self) -> dict:
        return {
            "status": self.status,
            "ok": self.ok,
            "reason": self.reason,
            "matched_node_id": self.matched_node_id,
            "matched_node_distance_m": (
                None
                if self.matched_node_distance_m is None
                else round(self.matched_node_distance_m, 3)
            ),
            "candidates": [candidate.to_metadata() for candidate in self.candidates],
        }


@dataclass(frozen=True)
class RouteArbitrationResult:
    """A typed arbitration outcome and the evidence behind it."""

    status: str
    reason: str
    model_direction: str | None
    pose: VehiclePose | None
    matched_node_id: str | None
    matched_node_distance_m: float | None
    candidates: tuple[RouteCandidate, ...]
    selected: RouteCandidate | None
    route_node_ids: tuple[str, ...]
    route_points: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if self.status not in RouteArbitrationStatus.ALL:
            raise ValueError(f"unknown arbitration status {self.status!r}")
        if self.status == RouteArbitrationStatus.SELECTED:
            if self.selected is None:
                raise ValueError("a selected arbitration requires a selected edge")
            if self.matched_node_id is None:
                raise ValueError("a selected arbitration requires a matched node")
        elif self.selected is not None:
            raise ValueError("a refused arbitration must not carry a selected edge")

    @property
    def ok(self) -> bool:
        return self.status == RouteArbitrationStatus.SELECTED

    @property
    def selected_edge(self) -> tuple[str, str] | None:
        if self.selected is None:
            return None
        return self.selected.from_node_id, self.selected.to_node_id

    @property
    def selected_route_node_ids(self) -> tuple[str, ...]:
        if self.selected is None or self.matched_node_id is None:
            return ()
        return (self.matched_node_id,) + self.selected.route_node_ids

    def to_metadata(self) -> dict:
        return {
            "status": self.status,
            "ok": self.ok,
            "reason": self.reason,
            "model_direction": self.model_direction,
            "pose": (
                None
                if self.pose is None
                else {
                    "x": self.pose.x,
                    "y": self.pose.y,
                    "heading": self.pose.heading,
                    "heading_deg": round(math.degrees(self.pose.heading), 3),
                }
            ),
            "matched_node_id": self.matched_node_id,
            "matched_node_distance_m": (
                None
                if self.matched_node_distance_m is None
                else round(self.matched_node_distance_m, 3)
            ),
            "candidates": [candidate.to_metadata() for candidate in self.candidates],
            "selected": None if self.selected is None else self.selected.to_metadata(),
            "selected_edge": (
                None
                if self.selected_edge is None
                else list(self.selected_edge)
            ),
            "route_node_ids": list(self.route_node_ids),
            "selected_route_node_ids": list(self.selected_route_node_ids),
            "route_points": [list(point) for point in self.route_points],
            "control_note": (
                "The result selects a high-level edge only. Throttle, brake and "
                "steer are produced by the CARLA controller, never by the model "
                "or by AgentIntent.target.heading."
            ),
        }


def execution_route(
    arbitration: RouteArbitrationResult, graph: RouteGraph
) -> tuple[tuple[str, ...], tuple[tuple[float, float], ...]]:
    """The one selected route that a controller may execute.

    This is the explicit boundary between arbitration and execution.  A
    selected result must carry the same node sequence and sampled points as
    the graph's selected route; a diagnostic root A* route is never accepted
    here.
    """

    if not isinstance(arbitration, RouteArbitrationResult):
        raise TypeError("arbitration must be a RouteArbitrationResult")
    if not isinstance(graph, RouteGraph):
        raise TypeError("graph must be a RouteGraph")
    if arbitration.status != RouteArbitrationStatus.SELECTED:
        raise ValueError(
            f"cannot execute a refused arbitration ({arbitration.status!r})"
        )
    nodes = arbitration.selected_route_node_ids
    if not nodes or arbitration.matched_node_id is None:
        raise ValueError("selected arbitration has no execution nodes")
    if nodes[0] != arbitration.matched_node_id:
        raise ValueError("selected route does not start at the matched node")
    if tuple(arbitration.route_node_ids) != tuple(nodes):
        raise ValueError(
            "arbitration route_node_ids differ from the selected route"
        )
    points = graph.points(nodes)
    if tuple(arbitration.route_points) != tuple(points):
        raise ValueError(
            "arbitration route_points differ from the selected graph route"
        )
    return tuple(nodes), tuple(points)


def _refuse(
    *,
    status: str,
    reason: str,
    model_direction: str | None,
    pose: VehiclePose | None = None,
    matched_node_id: str | None = None,
    matched_node_distance_m: float | None = None,
    candidates: tuple[RouteCandidate, ...] = (),
    route_node_ids: tuple[str, ...] = (),
    route_points: tuple[tuple[float, float], ...] = (),
) -> RouteArbitrationResult:
    return RouteArbitrationResult(
        status=status,
        reason=reason,
        model_direction=model_direction,
        pose=pose,
        matched_node_id=matched_node_id,
        matched_node_distance_m=matched_node_distance_m,
        candidates=candidates,
        selected=None,
        route_node_ids=route_node_ids,
        route_points=route_points,
    )


def _intent_error(
    intent: object, pose: VehiclePose, direction: str
) -> str | None:
    if not isinstance(intent, AgentIntent):
        return f"an AgentIntent is required, got {type(intent).__name__}"
    delta = DIRECTION_HEADING_DELTA[direction]
    expected_heading = normalize_heading(pose.heading + delta)
    if not math.isclose(intent.target.x, pose.x, rel_tol=0.0, abs_tol=1e-9):
        return (
            f"intent target.x={intent.target.x!r} does not match the real pose "
            f"x={pose.x!r}"
        )
    if not math.isclose(intent.target.y, pose.y, rel_tol=0.0, abs_tol=1e-9):
        return (
            f"intent target.y={intent.target.y!r} does not match the real pose "
            f"y={pose.y!r}"
        )
    if not math.isclose(
        normalize_heading(intent.target.heading),
        expected_heading,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        return (
            f"intent target.heading={intent.target.heading!r} does not match the "
            f"declared {direction} delta from the real pose heading"
        )
    return None


def _has_any_edge(graph: RouteGraph, node_id: str) -> bool:
    """True when the node participates in at least one executable edge."""

    if graph.neighbours(node_id):
        return True
    # Directed graphs can expose a node with only incoming edges; it is still
    # a graph node, but not a routable decision start.  Keep it in the pool so
    # the existing route/unreachable diagnostics still see it.
    return bool(graph.predecessors(node_id))


def _locate_node(
    graph: RouteGraph,
    pose: VehiclePose,
    *,
    expected_node_id: str | None,
    max_node_distance_m: float,
    ambiguity_margin_m: float,
) -> tuple[str | None, float | None, str | None]:
    # A node with no edge in either direction cannot be a routing decision
    # point.  The parking graph intentionally removes w8->w9 and w9->goal but
    # keeps w9 for the base map; including that isolated node made the real
    # park_entry pose look "equally close" to park_entry and w9 (0.26 m apart)
    # and refused an otherwise valid parking-arc decision.
    routable = {
        node_id for node_id in graph.nodes if _has_any_edge(graph, node_id)
    }
    if expected_node_id is not None and graph.has_node(expected_node_id):
        # Preserve the expected-node mismatch/unreachable diagnostics even if
        # the caller expects an isolated node.
        routable.add(expected_node_id)
    if not routable:
        routable = set(graph.nodes)
    distances = {
        node_id: math.hypot(node.x - pose.x, node.y - pose.y)
        for node_id, node in graph.nodes.items()
        if node_id in routable
    }
    nearest = min(distances, key=lambda node_id: (distances[node_id], node_id))
    nearest_distance = distances[nearest]
    if expected_node_id is not None:
        if not graph.has_node(expected_node_id):
            return None, None, f"expected node {expected_node_id!r} is not in the graph"
        if nearest != expected_node_id:
            return (
                None,
                nearest_distance,
                f"the real pose is nearest to {nearest!r} "
                f"({nearest_distance:.3f} m), not the expected node "
                f"{expected_node_id!r} "
                f"({distances[expected_node_id]:.3f} m)",
            )
    if nearest_distance > max_node_distance_m:
        return (
            None,
            nearest_distance,
            f"the real pose is {nearest_distance:.3f} m from the nearest node "
            f"{nearest!r}, beyond the {max_node_distance_m:.3f} m matching limit",
        )
    competitors = [
        node_id
        for node_id, distance in distances.items()
        if node_id != nearest
        and distance <= max_node_distance_m
        and abs(distance - nearest_distance) <= ambiguity_margin_m
    ]
    if competitors:
        return (
            None,
            nearest_distance,
            f"the real pose is equally close to {nearest!r} and "
            f"{sorted(competitors)!r}; the graph node cannot be identified",
        )
    return nearest, nearest_distance, None


def _build_candidates(
    graph: RouteGraph,
    node_id: str,
    pose: VehiclePose,
    goal_node_id: str,
    *,
    straight_tolerance_deg: float,
    turn_limit_deg: float,
    invert_turn_direction: bool,
    blocked: set[tuple[str, str]],
    pruned_nodes: set[str],
    direction: str | None,
) -> list[RouteCandidate]:
    """Classify every outgoing edge from ``node_id``.

    ``direction`` is ``None`` when the caller only wants the real branches
    (prompt context). In that case no edge is marked ``matches_direction`` and
    the rejection reason says why; selection logic must not run on that mode.
    """

    candidates: list[RouteCandidate] = []
    for neighbour, distance in graph.neighbours(node_id):
        # Use the edge's final tangent, not its chord: a curved branch can
        # leave the junction almost straight and only later become LEFT/RIGHT.
        bearing = graph.edge_end_bearing(node_id, neighbour)
        relative = wrap_angle(bearing - pose.heading)
        turn_class = classify_relative_turn(
            relative,
            straight_tolerance_deg=float(straight_tolerance_deg),
            turn_limit_deg=float(turn_limit_deg),
        )
        if invert_turn_direction:
            # CARLA's left-handed camera frame presents a positive relative
            # bearing on the image's right.  Scenes that define left/right by
            # the camera/image can opt into that convention explicitly.
            if turn_class == "LEFT":
                turn_class = "RIGHT"
            elif turn_class == "RIGHT":
                turn_class = "LEFT"
        if neighbour == goal_node_id:
            neighbour_route: list[str] | None = [goal_node_id]
            neighbour_status = None
        else:
            # The route after taking this edge must not immediately return to
            # the node it just left: that is a U-turn the direction vocabulary
            # cannot express, and on an undirected graph it can make a dead-end
            # branch look reachable through the very edge it is bypassing.
            neighbour_route, neighbour_status = graph.astar(
                neighbour,
                goal_node_id,
                excluded_edges={(node_id, neighbour)},
                excluded_nodes=pruned_nodes,
            )
        reachable = neighbour_route is not None
        blocked_edge = (node_id, neighbour) in blocked
        matches = (
            direction is not None
            and reachable
            and not blocked_edge
            and turn_class == direction
        )
        if not reachable:
            rejection = f"no path from {neighbour!r} to goal {goal_node_id!r}"
        elif blocked_edge:
            rejection = "edge is blocked by the real route safety check"
        elif direction is None:
            rejection = "the model direction is not available yet"
        elif not matches:
            rejection = (
                f"turn class {turn_class} does not match model direction "
                f"{direction}"
            )
        else:
            rejection = None
        candidates.append(
            RouteCandidate(
                from_node_id=node_id,
                to_node_id=neighbour,
                distance_m=float(distance),
                bearing_rad=bearing,
                relative_turn_rad=relative,
                turn_class=turn_class,
                reachable=reachable,
                matches_direction=matches,
                route_node_ids=tuple(neighbour_route or ()),
                rejection_reason=rejection,
                blocked=blocked_edge,
            )
        )
    return candidates


def route_candidates(
    graph: RouteGraph,
    pose: VehiclePose,
    goal_node_id: str,
    *,
    expected_node_id: str | None = None,
    max_node_distance_m: float = 2.0,
    ambiguity_margin_m: float = 0.5,
    straight_tolerance_deg: float = 15.0,
    turn_limit_deg: float = 150.0,
    invert_turn_direction: bool = False,
    blocked_edges: object = None,
    excluded_nodes: object = None,
) -> RouteCandidatesResult:
    """List the real outgoing edges the model must choose between.

    Uses exactly the localisation, exclusion and edge-classification rules of
    :func:`arbitrate_route`; the only difference is that no model direction is
    supplied, so nothing is selected. The result is prompt context, never an
    execution authorisation.
    """

    if not isinstance(graph, RouteGraph):
        raise TypeError("graph must be a RouteGraph")
    if not isinstance(pose, VehiclePose):
        raise TypeError("pose must be a VehiclePose")
    if not graph.has_node(goal_node_id):
        raise ValueError(f"goal node {goal_node_id!r} is not in the graph")

    blocked: set[tuple[str, str]] = set()
    pruned_nodes: set[str] = set()
    if excluded_nodes is not None:
        try:
            raw_excluded = tuple(excluded_nodes)
        except TypeError:
            raise TypeError("excluded_nodes must be an iterable of node ids") from None
        for node_id in raw_excluded:
            if not isinstance(node_id, str) or not graph.has_node(node_id):
                raise ValueError(f"excluded node {node_id!r} is not in the graph")
            pruned_nodes.add(node_id)
    if blocked_edges is not None:
        try:
            raw_blocked = tuple(blocked_edges)
        except TypeError:
            raise TypeError("blocked_edges must be an iterable of edge pairs") from None
        for edge in raw_blocked:
            if not isinstance(edge, (tuple, list)) or len(edge) != 2:
                raise ValueError("each blocked edge must be a (from, to) pair")
            a, b = edge
            if not isinstance(a, str) or not isinstance(b, str):
                raise ValueError("blocked edge endpoints must be strings")
            blocked.add((a, b))
            blocked.add((b, a))

    node_id, node_distance, locate_error = _locate_node(
        graph,
        pose,
        expected_node_id=expected_node_id,
        max_node_distance_m=float(max_node_distance_m),
        ambiguity_margin_m=float(ambiguity_margin_m),
    )
    if locate_error is not None:
        return RouteCandidatesResult(
            status=RouteCandidatesStatus.POSE_UNCERTAIN,
            reason=locate_error,
            pose=pose,
            matched_node_id=None,
            matched_node_distance_m=node_distance,
            candidates=(),
            route_node_ids=(),
            route_points=(),
        )
    assert node_id is not None
    root_route, root_status = graph.astar(
        node_id, goal_node_id, excluded_nodes=pruned_nodes
    )
    if root_route is None:
        return RouteCandidatesResult(
            status=RouteCandidatesStatus.UNREACHABLE_TARGET,
            reason=(
                f"node {node_id!r} cannot reach goal {goal_node_id!r} "
                f"(A* status {root_status!r})"
            ),
            pose=pose,
            matched_node_id=node_id,
            matched_node_distance_m=node_distance,
            candidates=(),
            route_node_ids=(),
            route_points=(),
        )
    candidates = _build_candidates(
        graph,
        node_id,
        pose,
        goal_node_id,
        straight_tolerance_deg=float(straight_tolerance_deg),
        turn_limit_deg=float(turn_limit_deg),
        invert_turn_direction=bool(invert_turn_direction),
        blocked=blocked,
        pruned_nodes=pruned_nodes,
        direction=None,
    )
    return RouteCandidatesResult(
        status=RouteCandidatesStatus.OK,
        reason=f"real outgoing edges from {node_id!r} to {goal_node_id!r}",
        pose=pose,
        matched_node_id=node_id,
        matched_node_distance_m=node_distance,
        candidates=tuple(candidates),
        route_node_ids=tuple(root_route),
        route_points=graph.points(root_route),
    )


def forward_reachable_candidates(
    graph: RouteGraph,
    node_id: str,
    heading_rad: float,
    goal_node_id: str,
    *,
    straight_tolerance_deg: float = 15.0,
    turn_limit_deg: float = 150.0,
    invert_turn_direction: bool = False,
    blocked_edges: object = None,
    excluded_nodes: object = None,
) -> tuple[RouteCandidate, ...]:
    """Outgoing edges the model could actually choose at ``node_id``.

    Same classification as :func:`arbitrate_route` (edge final tangent, turn
    vocabulary, no immediate U-turn back through the edge just used, goal
    reachability with the caller's exclusions). ``BEHIND`` edges are excluded:
    the direction vocabulary cannot express them, so they are not alternatives.

    ``blocked_edges`` carries the caller's fresh real clearance evidence. A
    candidate is returned with ``blocked=True`` when that evidence confirms an
    obstruction; an edge absent from the set is *not observed blocked* under
    that check, which is not a proof of safety. The caller decides what to do
    with unknown evidence.
    """

    if not isinstance(graph, RouteGraph):
        raise TypeError("graph must be a RouteGraph")
    if type(node_id) is not str or not graph.has_node(node_id):
        raise ValueError(f"node {node_id!r} is not in the graph")
    if not graph.has_node(goal_node_id):
        raise ValueError(f"goal node {goal_node_id!r} is not in the graph")
    if type(heading_rad) is not int and type(heading_rad) is not float:
        raise ValueError("heading_rad must be a number")
    if not math.isfinite(float(heading_rad)):
        raise ValueError("heading_rad must be finite")

    pruned_nodes: set[str] = set()
    if excluded_nodes is not None:
        try:
            raw_excluded = tuple(excluded_nodes)
        except TypeError:
            raise TypeError("excluded_nodes must be an iterable of node ids") from None
        for excluded in raw_excluded:
            if not isinstance(excluded, str) or not graph.has_node(excluded):
                raise ValueError(f"excluded node {excluded!r} is not in the graph")
            pruned_nodes.add(excluded)

    blocked: set[tuple[str, str]] = set()
    if blocked_edges is not None:
        try:
            raw_blocked = tuple(blocked_edges)
        except TypeError:
            raise TypeError("blocked_edges must be an iterable of edge pairs") from None
        for edge in raw_blocked:
            if not isinstance(edge, (tuple, list)) or len(edge) != 2:
                raise ValueError("each blocked edge must be a (from, to) pair")
            a, b = edge
            if not isinstance(a, str) or not isinstance(b, str):
                raise ValueError("blocked edge endpoints must be strings")
            blocked.add((a, b))
            blocked.add((b, a))

    node = graph.nodes[node_id]
    pose = VehiclePose(x=node.x, y=node.y, heading=float(heading_rad))
    candidates = _build_candidates(
        graph,
        node_id,
        pose,
        goal_node_id,
        straight_tolerance_deg=float(straight_tolerance_deg),
        turn_limit_deg=float(turn_limit_deg),
        invert_turn_direction=bool(invert_turn_direction),
        blocked=blocked,
        pruned_nodes=pruned_nodes,
        direction=None,
    )
    return tuple(
        candidate
        for candidate in candidates
        if candidate.reachable and candidate.turn_class in APPROVED_MODEL_DIRECTIONS
    )


def arbitrate_route(
    graph: RouteGraph,
    pose: VehiclePose,
    directive: object,
    *,
    intent: object,
    goal_node_id: str,
    expected_node_id: str | None = None,
    max_node_distance_m: float = 2.0,
    ambiguity_margin_m: float = 0.5,
    straight_tolerance_deg: float = 15.0,
    turn_limit_deg: float = 150.0,
    edge_ambiguity_tolerance_deg: float = 5.0,
    safety_ok: bool = True,
    invert_turn_direction: bool = False,
    blocked_edges: object = None,
    excluded_nodes: object = None,
) -> RouteArbitrationResult:
    """Select one graph edge compatible with the verified visual direction.

    All thresholds are explicit keyword arguments so the rule is both
    documented and testable. ``expected_node_id`` lets a multi-round caller
    require that the vehicle really reached the node selected last round; a
    mismatch is ``pose_uncertain`` rather than a silent re-localisation.
    """

    if not isinstance(graph, RouteGraph):
        raise TypeError("graph must be a RouteGraph")
    if not isinstance(pose, VehiclePose):
        raise TypeError("pose must be a VehiclePose")
    if not graph.has_node(goal_node_id):
        raise ValueError(f"goal node {goal_node_id!r} is not in the graph")

    blocked: set[tuple[str, str]] = set()
    pruned_nodes: set[str] = set()
    if excluded_nodes is not None:
        try:
            raw_excluded = tuple(excluded_nodes)
        except TypeError:
            raise TypeError("excluded_nodes must be an iterable of node ids") from None
        for node_id in raw_excluded:
            if not isinstance(node_id, str) or not graph.has_node(node_id):
                raise ValueError(f"excluded node {node_id!r} is not in the graph")
            pruned_nodes.add(node_id)
    if blocked_edges is not None:
        try:
            raw_blocked = tuple(blocked_edges)
        except TypeError:
            raise TypeError("blocked_edges must be an iterable of edge pairs") from None
        for edge in raw_blocked:
            if not isinstance(edge, (tuple, list)) or len(edge) != 2:
                raise ValueError("each blocked edge must be a (from, to) pair")
            a, b = edge
            if not isinstance(a, str) or not isinstance(b, str):
                raise ValueError("blocked edge endpoints must be strings")
            blocked.add((a, b))
            blocked.add((b, a))
    for name, value in (
        ("max_node_distance_m", max_node_distance_m),
        ("ambiguity_margin_m", ambiguity_margin_m),
        ("straight_tolerance_deg", straight_tolerance_deg),
        ("turn_limit_deg", turn_limit_deg),
        ("edge_ambiguity_tolerance_deg", edge_ambiguity_tolerance_deg),
    ):
        if type(value) is not int and type(value) is not float:
            raise ValueError(f"{name} must be a number")
        if not math.isfinite(float(value)) or value < 0:
            raise ValueError(f"{name} must be finite and non-negative")

    if not isinstance(directive, NavigationDirective):
        return _refuse(
            status=RouteArbitrationStatus.INVALID_INTENT,
            reason=(
                "arbitration accepts only a verified NavigationDirective, got "
                f"{type(directive).__name__}"
            ),
            model_direction=None,
            pose=pose,
        )
    direction = directive.direction
    if direction not in APPROVED_MODEL_DIRECTIONS:
        return _refuse(
            status=RouteArbitrationStatus.INVALID_INTENT,
            reason=(
                f"model direction {direction!r} is not one of "
                f"{list(APPROVED_MODEL_DIRECTIONS)}"
            ),
            model_direction=direction,
            pose=pose,
        )
    intent_problem = _intent_error(intent, pose, direction)
    if intent_problem is not None:
        return _refuse(
            status=RouteArbitrationStatus.INVALID_INTENT,
            reason=intent_problem,
            model_direction=direction,
            pose=pose,
        )
    if not safety_ok:
        return _refuse(
            status=RouteArbitrationStatus.SAFETY_UNSATISFIED,
            reason="the caller reported an unsatisfied safety precondition",
            model_direction=direction,
            pose=pose,
        )

    node_id, node_distance, locate_error = _locate_node(
        graph,
        pose,
        expected_node_id=expected_node_id,
        max_node_distance_m=float(max_node_distance_m),
        ambiguity_margin_m=float(ambiguity_margin_m),
    )
    if locate_error is not None:
        return _refuse(
            status=RouteArbitrationStatus.POSE_UNCERTAIN,
            reason=locate_error,
            model_direction=direction,
            pose=pose,
            matched_node_distance_m=node_distance,
        )

    assert node_id is not None
    root_route, root_status = graph.astar(
        node_id, goal_node_id, excluded_nodes=pruned_nodes
    )
    if root_route is None:
        return _refuse(
            status=RouteArbitrationStatus.UNREACHABLE_TARGET,
            reason=(
                f"node {node_id!r} cannot reach goal {goal_node_id!r} "
                f"(A* status {root_status!r})"
            ),
            model_direction=direction,
            pose=pose,
            matched_node_id=node_id,
            matched_node_distance_m=node_distance,
        )
    route_points = graph.points(root_route)

    candidates: list[RouteCandidate] = _build_candidates(
        graph,
        node_id,
        pose,
        goal_node_id,
        straight_tolerance_deg=float(straight_tolerance_deg),
        turn_limit_deg=float(turn_limit_deg),
        invert_turn_direction=bool(invert_turn_direction),
        blocked=blocked,
        pruned_nodes=pruned_nodes,
        direction=direction,
    )

    if not any(candidate.reachable for candidate in candidates):
        return _refuse(
            status=RouteArbitrationStatus.UNREACHABLE_TARGET,
            reason=(
                f"no outgoing edge from {node_id!r} reaches goal "
                f"{goal_node_id!r}"
            ),
            model_direction=direction,
            pose=pose,
            matched_node_id=node_id,
            matched_node_distance_m=node_distance,
            candidates=tuple(candidates),
            route_node_ids=tuple(root_route),
            route_points=route_points,
        )

    compatible = sorted(
        (candidate for candidate in candidates if candidate.matches_direction),
        key=lambda candidate: (abs(candidate.relative_turn_rad), candidate.to_node_id),
    )
    if not compatible:
        return _refuse(
            status=RouteArbitrationStatus.NO_COMPATIBLE_ROUTE,
            reason=(
                f"no reachable unblocked edge from {node_id!r} has turn class "
                f"{direction}; the visual direction conflicts with the feasible "
                "routes"
            ),
            model_direction=direction,
            pose=pose,
            matched_node_id=node_id,
            matched_node_distance_m=node_distance,
            candidates=tuple(candidates),
            route_node_ids=tuple(root_route),
            route_points=route_points,
        )
    if len(compatible) > 1:
        first, second = compatible[0], compatible[1]
        gap = abs(abs(first.relative_turn_rad) - abs(second.relative_turn_rad))
        if gap <= math.radians(float(edge_ambiguity_tolerance_deg)):
            return _refuse(
                status=RouteArbitrationStatus.AMBIGUOUS,
                reason=(
                    f"edges {first.from_node_id!r}->{first.to_node_id!r} and "
                    f"{second.from_node_id!r}->{second.to_node_id!r} are both "
                    f"{direction} with turn angles differing by only "
                    f"{math.degrees(gap):.3f} deg; no safe deterministic choice"
                ),
                model_direction=direction,
                pose=pose,
                matched_node_id=node_id,
                matched_node_distance_m=node_distance,
                candidates=tuple(candidates),
                route_node_ids=tuple(root_route),
                route_points=route_points,
            )

    selected = compatible[0]
    selected_route = (node_id,) + selected.route_node_ids
    selected_points = graph.points(selected_route)
    return RouteArbitrationResult(
        status=RouteArbitrationStatus.SELECTED,
        reason=(
            f"selected {selected.from_node_id!r}->{selected.to_node_id!r}: "
            f"{selected.turn_class} at {math.degrees(selected.relative_turn_rad):.3f} "
            f"deg relative to the real heading, reachable to {goal_node_id!r}"
        ),
        model_direction=direction,
        pose=pose,
        matched_node_id=node_id,
        matched_node_distance_m=node_distance,
        candidates=tuple(candidates),
        selected=selected,
        route_node_ids=selected_route,
        route_points=selected_points,
    )
