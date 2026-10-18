"""Deterministic candidate-route generation.

The algorithm is Yen's k-shortest loopless paths over the topological graph,
with geometric edge length as the search weight. It is small, deterministic and
explainable; no randomness is involved.

Important: generation deliberately ignores the scene's *current* blocked nodes
and edges. Otherwise an obstructed route would disappear from the candidate set
and the hard-constraint checker could not retain an explicit rejection reason.
Filtering happens only in :mod:`vln.planning_ltm.constraints`.
"""

from __future__ import annotations

import heapq
import math

from .errors import CandidateGenerationError
from .models import CandidateSet, ParkingScene, ParkingTopology, RouteCandidate

__all__ = ["generate_candidates", "MAX_CANDIDATES_LIMIT"]

MAX_CANDIDATES_LIMIT = 50


def _shortest_path(
    topology: ParkingTopology,
    start: str,
    goal: str,
    *,
    removed_nodes: frozenset[str] | set[str],
    removed_edges: frozenset[str] | set[str],
) -> tuple[str, ...] | None:
    """Dijkstra with a deterministic ``(distance, path)`` heap ordering."""

    heap: list[tuple[float, tuple[str, ...]]] = [(0.0, (start,))]
    best: dict[str, float] = {start: 0.0}
    while heap:
        distance, path = heapq.heappop(heap)
        node = path[-1]
        if distance > best.get(node, math.inf):
            continue
        if node == goal:
            return path
        for neighbor, edge_id in topology.neighbors(node):
            if neighbor in removed_nodes or edge_id in removed_edges:
                continue
            candidate_distance = distance + topology.edge_length(edge_id)
            if candidate_distance < best.get(neighbor, math.inf):
                best[neighbor] = candidate_distance
                heapq.heappush(heap, (candidate_distance, path + (neighbor,)))
    return None


def _yen_k_shortest_paths(
    topology: ParkingTopology, start: str, goal: str, count: int
) -> list[tuple[str, ...]]:
    first = _shortest_path(
        topology, start, goal, removed_nodes=frozenset(), removed_edges=frozenset()
    )
    if first is None:
        return []

    accepted: list[tuple[str, ...]] = [first]
    candidates: list[tuple[float, tuple[str, ...]]] = []
    queued: set[tuple[str, ...]] = set()

    while len(accepted) < count:
        previous = accepted[-1]
        for index in range(len(previous) - 1):
            spur_node = previous[index]
            root = previous[: index + 1]
            removed_edges: set[str] = set()
            for path in accepted:
                if len(path) > index + 1 and path[: index + 1] == root:
                    edge = topology.edge_between(path[index], path[index + 1])
                    if edge is not None:
                        removed_edges.add(edge.edge_id)
            removed_nodes = set(root[:-1])
            spur_path = _shortest_path(
                topology,
                spur_node,
                goal,
                removed_nodes=removed_nodes,
                removed_edges=removed_edges,
            )
            if spur_path is None:
                continue
            total = root + spur_path[1:]
            if total in accepted or total in queued:
                continue
            queued.add(total)
            heapq.heappush(candidates, (topology.route_length(total), total))

        if not candidates:
            break
        _, path = heapq.heappop(candidates)
        queued.discard(path)
        accepted.append(path)

    return accepted


def generate_candidates(
    scene: ParkingScene, *, max_candidates: int = 3
) -> CandidateSet:
    """Generate up to ``max_candidates`` distinct loopless routes to the target.

    Fewer routes than requested are returned honestly together with
    :attr:`CandidateSet.insufficient_reason`; no substitute route is invented.
    """

    if type(max_candidates) is not int or max_candidates < 1:
        raise CandidateGenerationError("max_candidates must be a positive integer")
    if max_candidates > MAX_CANDIDATES_LIMIT:
        raise CandidateGenerationError(
            f"max_candidates must be <= {MAX_CANDIDATES_LIMIT}"
        )

    paths = _yen_k_shortest_paths(
        scene.topology,
        scene.start_node_id,
        scene.target_node_id,
        max_candidates,
    )
    candidates: list[RouteCandidate] = []
    for index, node_ids in enumerate(paths):
        edge_ids: list[str] = []
        for first, second in zip(node_ids, node_ids[1:]):
            edge = scene.topology.edge_between(first, second)
            if edge is None:
                raise CandidateGenerationError(
                    f"generated route is not connected: {first!r} -> {second!r}"
                )
            edge_ids.append(edge.edge_id)
        candidates.append(
            RouteCandidate(
                candidate_id=f"cand-{scene.scene_id}-{index + 1:02d}",
                target_id=scene.target_id,
                node_ids=node_ids,
                edge_ids=tuple(edge_ids),
                length_m=scene.topology.route_length(node_ids),
            )
        )

    return CandidateSet(
        scene_id=scene.scene_id,
        target_id=scene.target_id,
        requested_count=max_candidates,
        candidates=tuple(candidates),
    )
