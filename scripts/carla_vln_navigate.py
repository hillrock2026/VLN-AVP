#!/usr/bin/env python3
"""M1-VLN-CARLA-01E: multi-round model navigation to a declared goal region.

Each round is exactly one closed-loop step over the validated 01B graph:

    real CARLA state + fresh RGB frame
      -> existing 01C observation adapter
      -> real ZDTaichu5.0-9B request through ServerImageModelClient
      -> existing parse_visual_decision -> verify_visual_decision -> to_agent_intent
      -> vln.carla.arbitrate_route (relative bearing + graph reachability)
      -> shared 01B Pure Pursuit / safety / SegmentMonitor
      -> CARLA VehicleControl -> stopped state + fresh frame for the next round

The model can only choose a graph edge. Throttle, brake and steering are
produced by the shared controller; no model number and no
AgentIntent.target.heading is ever applied to the vehicle.

The reproducible route starts at ``w4`` and ends at the 01B ``goal`` node
``(-4, -20)``. Candidate edges are classified relative to the vehicle's real
heading with a 10-degree straight deadband. The task stops on one of the
explicit states in :class:`TaskStatus`; ``goal_reached`` requires the real
stopped pose to satisfy distance, heading and stop-speed conditions.

Exit codes: 0 goal reached, 2 partial / safe stop / not reached, 3 model
unavailable, 4 setup or capture failure, 5 unexpected error.

This script does not start, stop or reconfigure the Taichu service. The
companion launcher may start/stop its own CARLA server.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import carla  # noqa: E402  (only available in the CARLA venv)

import carla_parking_nav as nav01b  # noqa: E402
from carla_video_recorder import VideoRecorder  # noqa: E402
import carla_vln_observe as observe01c  # noqa: E402
from vln.carla import (  # noqa: E402
    BAY03_CENTER,
    BAY03_ID,
    BAY03_POLYGON,
    BAY11_CENTER,
    BAY11_ID,
    BAY11_POLYGON,
    GOAL_REACHED,
    INTENT_REJECTED,
    MODEL_OUTPUT_INVALID,
    MODEL_REQUEST_FAILED,
    PARKING_FOOTPRINT,
    PARKING_SLOT_HEADING_RAD,
    SUCCESS,
    CameraFrame,
    CarlaVisualObservation,
    ControlCommand,
    Footprint,
    GoalSpec,
    RouteArbitrationStatus,
    SegmentMonitor,
    TaskStatus,
    arbitrate_route,
    build_round_linkage,
    build_stop_diagnostics,
    cumulative_lengths,
    evaluate_goal,
    evaluate_parking_verdict,
    execution_route,
    footprint_clearance,
    forward_safety_verdict,
    generate_and_decide,
    may_drive,
    parking_track_command,
    path_clearance,
    point_at_s,
    project_to_path,
    pure_pursuit_command,
    resolve_task_status,
    underground_carpark_graph,
    write_rgb_png,
)
from vln.carla.kernel_bridge import CarlaExecutionBridge  # noqa: E402
from vln.carla.parking_control import (  # noqa: E402
    parking_continuation_target_index,
    parking_execution_budget,
    parking_precheck_origin_start,
)
from vln.carla.route_redecision import (  # noqa: E402
    RouteRedecisionStatus,
    build_route_facts_from_candidates,
    format_route_facts,
    run_route_redecision,
)
from vln.carla.route_arbitration import (  # noqa: E402
    forward_reachable_candidates,
    route_candidates,
)
from vln.navigation.recovery import (  # noqa: E402
    RecoverySkillInput,
    evaluate_navigation_recovery,
)
from vln.carla.route_selection import resolve_route  # noqa: E402
from vln.carla.session import cleanup_session  # noqa: E402
from vln.carla.town10_fork import (  # noqa: E402
    TOWN10_FORK_GOAL_A,
    TOWN10_FORK_GOAL_B,
    TOWN10_FORK_START_NODE,
    town10_fork_graph,
)
from vln.carla.town10_multipoint import (  # noqa: E402
    TOWN10_MULTIPOINT_GOAL_NODE,
    TOWN10_MULTIPOINT_START_NODE,
    town10_multipoint_graph,
)
from vln.carla.town10_recovery import (  # noqa: E402
    TOWN10_RECOVERY_GOAL_NODE,
    TOWN10_RECOVERY_START_NODE,
    town10_recovery_graph,
)
from vln.carla.town10_recovery_east import (  # noqa: E402
    TOWN10_RECOVERY_EAST_GOAL_NODE,
    TOWN10_RECOVERY_EAST_START_NODE,
    town10_recovery_east_graph,
)
from vln.carla.town10_recovery_upstream import (  # noqa: E402
    TOWN10_RECOVERY_UPSTREAM_GOAL_NODE,
    TOWN10_RECOVERY_UPSTREAM_START_NODE,
    town10_recovery_upstream_graph,
)
from vln.carla.town10_continuation import (  # noqa: E402
    TOWN10_CONTINUATION_GOAL_NODE,
    TOWN10_CONTINUATION_START_NODE,
    town10_continuation_graph,
)
from vln.carla.underground_carpark_parking import (  # noqa: E402
    BAY11_SLOT_NODE_ID,
    BAY11_TURN_NODE_ID,
    BYPASS_NODE_IDS,
    PARK_JOIN_NODE_ID,
    RECOVERY_ENTRY_NODE_IDS,
    SECOND_BYPASS_ENTRY_NODE_ID,
    SECOND_BYPASS_JOIN_NODE_ID,
    SECOND_BYPASS_LEFT_NODE_ID,
    UNDERGROUND_CARPARK_PARKING_ENTRY_NODE,
    UNDERGROUND_CARPARK_PARKING_GOAL_NODE,
    UNDERGROUND_CARPARK_PARKING_START_NODE,
    underground_carpark_parking_graph,
)
from vln.client import HostClient, build_request  # noqa: E402
from vln.intent import AgentIntent, Target  # noqa: E402
from vln.ipc.envelope import HostKind, Request  # noqa: E402
from vln.nav import VehiclePose  # noqa: E402
from vln.nav.binding_runtime import (  # noqa: E402
    BindingRuntimeError,
    load_binding_artifact,
    resolve_bound_goal,
)
from vln.nav.visual_recovery import (  # noqa: E402
    RecoveryBudget,
    RecoveryRefused,
    VisualRecoveryAction,
    VisualRecoveryMachine,
    classify_visual_uncertainty,
    ensure_context_revision_advanced,
    reobservation_note,
    require_new_observation,
)
from vln.carla.target_approach import (  # noqa: E402
    approach_node_for_slot,
    evaluate_target_approach,
)
from vln.stm import NavigationTaskMemory, RoundOutcome  # noqa: E402
from vln.vlm.host_planner_client import HostPlannerModelClient  # noqa: E402
from vln.vlm.image_path_client import ServerImageModelClient  # noqa: E402
from vln.vlm.nav_prompt import Variant, build_nav_prompt  # noqa: E402
from vln.vlm.server_client import ZDTaichuServerBackend  # noqa: E402

MAP_NAME = "UndergroundCarPark"
CAM_W, CAM_H = 1280, 720
CAM_OFFSET = (-4.0, 0.0, 2.0)
CAM_PITCH = -5.0
EGO_ROLE = "vln_ego_01e"
CAM_ROLE = "vln_cam_01e"
COLLISION_ROLE = "vln_collision_demo02"
DEFAULT_START_NODE = "w4"
DEFAULT_GOAL_NODE = "goal"
FLOOR_Z = 5.80
FLOOR_PROBE_Z = 7.0
SAFETY_RAY_Z_OFFSET = 0.35
SPAWN_Z_MIN, SPAWN_Z_MAX = 5.0, 8.0
INVERT_TURN_DIRECTION = False
SCENARIO = "carpark"
FIXED_DT = 0.05
STRAIGHT_TOLERANCE_DEG = 10.0
TURN_LIMIT_DEG = 150.0
EDGE_AMBIGUITY_DEG = 5.0
ARRIVAL_RADIUS_M = 0.75
MAX_NODE_DISTANCE_M = 2.0
GOAL_DISTANCE_TOLERANCE_M = 1.5
GOAL_HEADING_TOLERANCE_DEG = 30.0
GOAL_STOP_SPEED_MPS = 0.25

EXIT_PASS = 0
EXIT_PARTIAL = 2
EXIT_MODEL = 3
EXIT_SETUP = 4
EXIT_UNEXPECTED = 5

TASK_LABEL = "M1-VLN-CARLA-06"
# Parking-domain progress snapshot carried in the Agent-Kernel Context.
PARKING_CONTEXT: dict | None = None
PROJECTION_WINDOW_M = 30.0
PRECHECK_RAY_Z_OFFSETS = None
PRECHECK_LATERAL_OFFSETS = None
PRECHECK_PATH_ORIGIN_S = None

# DEMO-02 final-parking phase.  The static clearance guard uses the 07A
# measured obstacle points, the same evidence as the parking scene geometry.
PARKING_STATIC_CLEARANCE_M = 0.2
PARKING_STOP_DISTANCE_M = 1.0
PARKING_SUCCESS_DISTANCE_M = 0.12
PARKING_SUCCESS_HEADING_DEG = 3.0
PARKING_STOP_STABLE_TICKS = 20
PARKING_PROBE_JSON = REPO_ROOT / "docs" / "evidence" / "carla-07a" / "geometry_probe.json"
PARKING_CORRIDOR_PRECHECK_STEP_M = 1.5
OBSTACLE_ROLE = "vln_obstacle_demo03"
_RUN_COLLISION_EVENTS: list[dict] = []
_RUN_EXTRA_OBSTACLES: list[tuple[float, float]] = []
_RUN_OBSTACLE_RECORDS: list[dict] = []
_RUN_OBSTACLE_TRIGGERS: list[dict] = []
_RUN_COLLISION_LOCK = threading.Lock()
_PARKING_OBSTACLES: tuple[tuple[float, float], ...] | None = None

# One parking-target spec per reachable bay goal. The goal node comes from the
# CLI; the execution, final heading and independent verdict use the same spec.
PARKING_GOAL_SPECS = {
    UNDERGROUND_CARPARK_PARKING_GOAL_NODE: {
        "bay_id": BAY03_ID,
        "bay_polygon": BAY03_POLYGON,
        "bay_center": BAY03_CENTER,
    },
    BAY11_SLOT_NODE_ID: {
        "bay_id": BAY11_ID,
        "bay_polygon": BAY11_POLYGON,
        "bay_center": BAY11_CENTER,
    },
}
PARKING_GOAL_NODES = frozenset(PARKING_GOAL_SPECS)
# Entry/turn points of the validated parking arcs. They are arc points, not
# high-level decision points; an approved route continues through them to the
# parking goal even when the requested segment boundary lands on one of them.
PARKING_ARC_ENTRY_NODE_IDS = frozenset(
    {
        UNDERGROUND_CARPARK_PARKING_ENTRY_NODE,
        BAY11_TURN_NODE_ID,
    }
)


def _parking_obstacle_points() -> tuple[tuple[float, float], ...]:
    global _PARKING_OBSTACLES
    if _PARKING_OBSTACLES is None:
        try:
            payload = json.loads(PARKING_PROBE_JSON.read_text(encoding="utf-8"))
            _PARKING_OBSTACLES = tuple(
                (float(point[0]), float(point[1]))
                for point in payload["obstacle_points"]
            )
        except (OSError, ValueError, KeyError, TypeError):
            _PARKING_OBSTACLES = ()
    return _PARKING_OBSTACLES


def _collision_count() -> int:
    with _RUN_COLLISION_LOCK:
        return len(_RUN_COLLISION_EVENTS)


def _collision_snapshot() -> list[dict]:
    with _RUN_COLLISION_LOCK:
        return list(_RUN_COLLISION_EVENTS)


def _all_parking_obstacles() -> tuple[tuple[float, float], ...]:
    return tuple(_parking_obstacle_points()) + tuple(_RUN_EXTRA_OBSTACLES)


def _parking_precheck_plan(route_node_ids, target_node_id, start_s=0.0):
    """Corridor origins and stop distance for a real route precheck.

    The parking scenario must look down the whole corridor (not only the
    first tangent) because the graph nodes are shorter than the car.  The
    origins stop at the parking entry/join so the planned 2.6 m wall gap at
    the final bay pose is not mistaken for a driving obstacle; the parking
    segment keeps its own 1.0 m stop distance.
    """

    if SCENARIO != "carpark_parking":
        return None, None
    start_id = None
    for candidate in (
        "park_entry",
        PARK_JOIN_NODE_ID,
        SECOND_BYPASS_JOIN_NODE_ID,
        BAY11_TURN_NODE_ID,
    ):
        if candidate in route_node_ids:
            start_id = candidate
            break
    if start_id is None:
        return None, None
    index = list(route_node_ids).index(start_id)
    prefix_ids = list(route_node_ids)[: index + 1]
    if len(prefix_ids) < 2:
        prefix_ids = list(route_node_ids)[:2]
    prefix = GRAPH.points(prefix_ids)
    s_end = 0.0 if index == 0 else cumulative_lengths(prefix)[-1]
    origins = []
    # A path-origin ray starts at z=ego_z+0.35. Inside the 5.006 m body that
    # point hits the ego itself at distance 0.0 and blocks a valid route, so
    # the first origin must follow the real projection beyond the body.
    s = parking_precheck_origin_start(
        start_s,
        half_length_m=PARKING_FOOTPRINT.half_length,
        front_margin_m=PARKING_FOOTPRINT.front_margin,
    )
    while s <= s_end + 1e-6:
        origins.append(round(s, 3))
        s += PARKING_CORRIDOR_PRECHECK_STEP_M
    stop = (
        PARKING_STOP_DISTANCE_M
        if target_node_id in PARKING_GOAL_NODES
        else None
    )
    return (tuple(origins) if origins else None), stop


def _blocked_candidate_edges(
    matched_node_id: str,
    goal_node_id: str = UNDERGROUND_CARPARK_PARKING_GOAL_NODE,
    excluded_nodes: object = None,
) -> tuple[set, list]:
    """Real route-clearance check for every outgoing recovery candidate."""

    obstacles = _all_parking_obstacles()
    blocked: set[tuple[str, str]] = set()
    evidence = []
    for neighbour, _distance in GRAPH.neighbours(matched_node_id):
        if neighbour == goal_node_id:
            route = [goal_node_id]
        else:
            # Do not let the route return through the node it just left; that
            # would make the bypass check meaningless on an undirected graph.
            route, _status = GRAPH.astar(
                neighbour,
                goal_node_id,
                excluded_edges={(matched_node_id, neighbour)},
                excluded_nodes=excluded_nodes,
            )
        route_nodes = [matched_node_id] + list(route or [])
        if route is None:
            evidence.append(
                {
                    "from_node_id": matched_node_id,
                    "to_node_id": neighbour,
                    "route_node_ids": route_nodes,
                    "route_reachable": False,
                    "min_clearance_m": None,
                    "worst": None,
                    "blocked": False,
                }
            )
            continue
        points = GRAPH.points(route_nodes)
        clearance = path_clearance(
            points,
            PARKING_FOOTPRINT,
            obstacles,
            sample_step_m=0.1,
        )
        minimum = clearance.get("min_clearance_m")
        is_blocked = (
            minimum is not None and minimum < PARKING_STATIC_CLEARANCE_M
        )
        if is_blocked:
            blocked.add((matched_node_id, neighbour))
        evidence.append(
            {
                "from_node_id": matched_node_id,
                "to_node_id": neighbour,
                "route_node_ids": route_nodes,
                "route_reachable": route is not None,
                "min_clearance_m": minimum,
                "worst": clearance.get("worst_pose"),
                "blocked": is_blocked,
            }
        )
    return blocked, evidence


def _spawn_demo_obstacle(
    session,
    world,
    blueprint_name: str,
    x: float,
    y: float,
    z: float,
    yaw: float,
    label: str,
    *,
    phase: str = "round_start",
    progress_m: float | None = None,
) -> dict:
    """Create one real static obstacle and return its traceable record."""

    blueprint = world.get_blueprint_library().find(blueprint_name)
    role = f"{OBSTACLE_ROLE}_{label}"
    if blueprint.has_attribute("role_name"):
        blueprint.set_attribute("role_name", role)
    actor = world.try_spawn_actor(
        blueprint,
        carla.Transform(
            carla.Location(x=float(x), y=float(y), z=float(z)),
            carla.Rotation(yaw=float(yaw)),
        ),
    )
    if actor is None:
        raise RuntimeError(
            f"obstacle spawn failed for {blueprint_name} at ({x:.2f},{y:.2f})"
        )
    session.actors.append(actor)
    frame = int(session.world.get_snapshot().frame)
    bbox = None
    obstacle_points: list[tuple[float, float]] = []
    try:
        extent = actor.bounding_box
        # Use the requested spawn pose: a just-spawned actor's get_transform()
        # can still be the identity until the next world tick, and the obstacle
        # points must be in the same world frame as the route.
        world_tf = carla.Transform(
            carla.Location(x=float(x), y=float(y), z=float(z)),
            carla.Rotation(yaw=float(yaw)),
        )
        corners = [
            world_tf.transform(
                carla.Location(
                    x=extent.location.x + sx * extent.extent.x,
                    y=extent.location.y + sy * extent.extent.y,
                    z=extent.location.z,
                )
            )
            for sx in (-1.0, 1.0)
            for sy in (-1.0, 1.0)
        ]
        obstacle_points = [(corner.x, corner.y) for corner in corners]
        bbox = {
            "half_length_m": round(float(extent.extent.x), 3),
            "half_width_m": round(float(extent.extent.y), 3),
            "half_height_m": round(float(extent.extent.z), 3),
            "world_corners": [
                [round(corner.x, 3), round(corner.y, 3)] for corner in corners
            ],
        }
    except Exception:
        bbox = None
        obstacle_points = []
    record = {
        "label": label,
        "phase": phase,
        "blueprint": blueprint_name,
        "role_name": role,
        "actor_id": int(actor.id),
        "x": round(float(x), 3),
        "y": round(float(y), 3),
        "z": round(float(z), 3),
        "yaw_deg": round(float(yaw), 3),
        "bbox": bbox,
        "obstacle_points": [
            [round(point[0], 3), round(point[1], 3)]
            for point in obstacle_points
        ],
        "progress_m": None if progress_m is None else round(float(progress_m), 3),
        "injected_frame": frame,
        "injected_utc": utc_now(),
        "spawned": True,
    }
    _RUN_EXTRA_OBSTACLES.append((float(x), float(y)))
    _RUN_EXTRA_OBSTACLES.extend(obstacle_points)
    _RUN_OBSTACLE_RECORDS.append(record)
    return record


def _remove_injected_obstacles(session, round_index: int) -> list[dict]:
    """Destroy every injected real obstacle and drop its clearance points.

    Used to test a controlled real state change: an edge that was blocked in
    one round must be re-evaluated from fresh evidence later, not locked by a
    stale verdict.
    """

    world = session.world
    frame = int(world.get_snapshot().frame)
    removed: list[dict] = []
    for record in _RUN_OBSTACLE_RECORDS:
        if record.get("removed") or not record.get("spawned"):
            continue
        error = None
        actor_id = record.get("actor_id")
        actor = world.get_actor(actor_id) if actor_id is not None else None
        if actor is not None:
            try:
                actor.destroy()
            except Exception as exc:  # keep removing the remaining obstacles
                error = f"{type(exc).__name__}: {exc}"
        points = [(float(record.get("x", 0.0)), float(record.get("y", 0.0)))]
        points.extend(
            (float(point[0]), float(point[1]))
            for point in record.get("obstacle_points") or []
        )
        kept = [
            point
            for point in _RUN_EXTRA_OBSTACLES
            if all(
                (point[0] - qx) ** 2 + (point[1] - qy) ** 2 > 1e-6
                for qx, qy in points
            )
        ]
        _RUN_EXTRA_OBSTACLES[:] = kept
        record["removed"] = True
        record["removed_round"] = round_index
        record["removed_frame"] = frame
        record["removed_utc"] = utc_now()
        record["removal_error"] = error
        removed.append(
            {
                "label": record.get("label"),
                "actor_id": record.get("actor_id"),
                "x": record.get("x"),
                "y": record.get("y"),
                "removed_round": round_index,
                "removed_frame": frame,
                "removal_error": error,
            }
        )
    return removed


def _apply_obstacle_triggers(session, progress_s, route_node_ids) -> list[dict]:
    """Spawn any armed mid-segment obstacle once this route reaches its s.

    The trigger is armed after model arbitration and before execution, so the
    pre-execution route check cannot see it.  It is spawned from inside the
    Kernel-invoked controller loop, exactly where a real obstruction would
    appear in front of the moving vehicle.
    """

    spawned = []
    if not _RUN_OBSTACLE_TRIGGERS:
        return spawned
    route_key = [str(node_id) for node_id in route_node_ids]
    for trigger in _RUN_OBSTACLE_TRIGGERS:
        if trigger.get("spawned") is True:
            continue
        if trigger.get("route_node_ids") != route_key:
            continue
        if float(progress_s) < float(trigger["trigger_s"]):
            continue
        record = _spawn_demo_obstacle(
            session,
            session.world,
            trigger["blueprint"],
            trigger["x"],
            trigger["y"],
            trigger["z"],
            trigger["yaw_deg"],
            trigger["label"],
            phase="mid_segment",
            progress_m=trigger["cone_s"],
        )
        record["trigger_s"] = round(float(trigger["trigger_s"]), 3)
        record["vehicle_progress_m"] = round(float(progress_s), 3)
        trigger["spawned"] = True
        trigger["spawned_frame"] = record["injected_frame"]
        spawned.append(record)
    return spawned


def _nearest_recovery_node(post_state) -> tuple[str | None, float | None, str | None]:
    """Match the real post-stop pose to exactly one graph node."""

    if not isinstance(post_state, dict):
        return None, None, "the failed segment has no post-stop state"
    distances = {
        node_id: math.hypot(node.x - post_state["x"], node.y - post_state["y"])
        for node_id, node in GRAPH.nodes.items()
    }
    nearest = min(distances, key=lambda node_id: (distances[node_id], node_id))
    nearest_distance = distances[nearest]
    if nearest_distance > MAX_NODE_DISTANCE_M:
        return (
            None,
            nearest_distance,
            f"the post-stop pose is {nearest_distance:.3f} m from the nearest "
            f"node {nearest!r}, beyond the {MAX_NODE_DISTANCE_M:.3f} m limit",
        )
    competitors = [
        node_id
        for node_id, distance in distances.items()
        if node_id != nearest
        and distance <= MAX_NODE_DISTANCE_M
        and abs(distance - nearest_distance) <= 0.5
    ]
    if competitors:
        return (
            None,
            nearest_distance,
            f"the post-stop pose is equally close to {nearest!r} and "
            f"{sorted(competitors)!r}",
        )
    return nearest, nearest_distance, None


def _forward_candidates(
    node_id: str,
    goal_node_id: str,
    heading_rad: float,
    *,
    blocked_edges: object = None,
    excluded_nodes: object = None,
):
    """Forward, goal-reachable candidates under the arbitration's own rules.

    ``blocked_edges`` is the caller's fresh clearance evidence; each candidate
    keeps its ``blocked`` flag so the caller can distinguish confirmed blocked
    from merely-not-observed-blocked.
    """

    return forward_reachable_candidates(
        GRAPH,
        node_id,
        heading_rad,
        goal_node_id,
        straight_tolerance_deg=STRAIGHT_TOLERANCE_DEG,
        turn_limit_deg=TURN_LIMIT_DEG,
        invert_turn_direction=INVERT_TURN_DIRECTION,
        blocked_edges=blocked_edges,
        excluded_nodes=excluded_nodes,
    )


def _recovery_selected_edges_unblocked(result: dict) -> bool:
    blocked_evidence = [
        item
        for group in result.get("recovery_blocked_edges", [])
        for item in group.get("evidence", [])
    ]
    selected = [
        item.get("selected_edge") or item.get("recovery_selected_edge")
        for item in result.get("recoveries", [])
        if item.get("selected_edge") or item.get("recovery_selected_edge")
    ]
    if not selected:
        return False
    for edge in selected:
        for evidence in blocked_evidence:
            if (
                evidence.get("blocked") is True
                and [evidence.get("from_node_id"), evidence.get("to_node_id")]
                == list(edge)
            ):
                return False
    return True


GRAPH = underground_carpark_graph()
NODES = {name: (node.x, node.y) for name, node in GRAPH.nodes.items()}


def configure_scenario(name: str) -> None:
    """Select the map/graph/floor profile used by the existing runner."""

    global MAP_NAME, GRAPH, NODES, SCENARIO
    global DEFAULT_START_NODE, DEFAULT_GOAL_NODE
    global FLOOR_Z, FLOOR_PROBE_Z, SAFETY_RAY_Z_OFFSET
    global PRECHECK_RAY_Z_OFFSETS
    global PRECHECK_LATERAL_OFFSETS
    global PRECHECK_PATH_ORIGIN_S
    global SPAWN_Z_MIN, SPAWN_Z_MAX, INVERT_TURN_DIRECTION
    if name == "carpark":
        MAP_NAME = "UndergroundCarPark"
        GRAPH = underground_carpark_graph()
        DEFAULT_START_NODE = "w4"
        DEFAULT_GOAL_NODE = "goal"
        FLOOR_Z = 5.80
        FLOOR_PROBE_Z = 7.0
        SAFETY_RAY_Z_OFFSET = 0.35
        SPAWN_Z_MIN, SPAWN_Z_MAX = 5.0, 8.0
        INVERT_TURN_DIRECTION = False
    elif name == "carpark_parking":
        MAP_NAME = "UndergroundCarPark"
        GRAPH = underground_carpark_parking_graph()
        DEFAULT_START_NODE = UNDERGROUND_CARPARK_PARKING_START_NODE
        DEFAULT_GOAL_NODE = UNDERGROUND_CARPARK_PARKING_GOAL_NODE
        FLOOR_Z = 5.80
        FLOOR_PROBE_Z = 7.0
        SAFETY_RAY_Z_OFFSET = 0.35
        SPAWN_Z_MIN, SPAWN_Z_MAX = 5.0, 8.0
        INVERT_TURN_DIRECTION = False
    elif name == "town10_fork":
        MAP_NAME = "Town10HD_Opt"
        GRAPH = town10_fork_graph()
        DEFAULT_START_NODE = TOWN10_FORK_START_NODE
        DEFAULT_GOAL_NODE = TOWN10_FORK_GOAL_A
        FLOOR_Z = 0.0
        FLOOR_PROBE_Z = 1.0
        # The crosswalk trigger geometry sits below 2 m and is not a physical
        # obstacle; the collision sensor remains active in the CARLA session.
        SAFETY_RAY_Z_OFFSET = 2.5
        SPAWN_Z_MIN, SPAWN_Z_MAX = 0.0, 2.0
        # Town10's camera/image left-right is opposite the world-math sign.
        INVERT_TURN_DIRECTION = True
    elif name == "town10_multipoint":
        MAP_NAME = "Town10HD_Opt"
        GRAPH = town10_multipoint_graph()
        DEFAULT_START_NODE = TOWN10_MULTIPOINT_START_NODE
        DEFAULT_GOAL_NODE = TOWN10_MULTIPOINT_GOAL_NODE
        FLOOR_Z = 0.0
        FLOOR_PROBE_Z = 1.0
        SAFETY_RAY_Z_OFFSET = 2.5
        SPAWN_Z_MIN, SPAWN_Z_MAX = 0.0, 2.0
        INVERT_TURN_DIRECTION = True
    elif name == "town10_recovery":
        MAP_NAME = "Town10HD_Opt"
        GRAPH = town10_recovery_graph()
        DEFAULT_START_NODE = TOWN10_RECOVERY_START_NODE
        DEFAULT_GOAL_NODE = TOWN10_RECOVERY_GOAL_NODE
        FLOOR_Z = 0.0
        FLOOR_PROBE_Z = 1.0
        SAFETY_RAY_Z_OFFSET = 2.5
        SPAWN_Z_MIN, SPAWN_Z_MAX = 0.0, 2.0
        INVERT_TURN_DIRECTION = True
    elif name == "town10_recovery_east":
        MAP_NAME = "Town10HD_Opt"
        GRAPH = town10_recovery_east_graph()
        DEFAULT_START_NODE = TOWN10_RECOVERY_EAST_START_NODE
        DEFAULT_GOAL_NODE = TOWN10_RECOVERY_EAST_GOAL_NODE
        # The j2c junction rises from z=0.059 m to z=0.139 m at n1; the
        # validation tolerance stays the existing +/-0.10 m.
        FLOOR_Z = 0.10
        FLOOR_PROBE_Z = 1.0
        SAFETY_RAY_Z_OFFSET = 2.5
        SPAWN_Z_MIN, SPAWN_Z_MAX = 0.0, 2.0
        INVERT_TURN_DIRECTION = True
    elif name == "town10_recovery_upstream":
        MAP_NAME = "Town10HD_Opt"
        GRAPH = town10_recovery_upstream_graph()
        DEFAULT_START_NODE = TOWN10_RECOVERY_UPSTREAM_START_NODE
        DEFAULT_GOAL_NODE = TOWN10_RECOVERY_UPSTREAM_GOAL_NODE
        # Upstream road-19/296 and the j2c junction span z=0.001..0.139 m.
        FLOOR_Z = 0.05
        FLOOR_PROBE_Z = 1.0
        SAFETY_RAY_Z_OFFSET = 2.5
        SPAWN_Z_MIN, SPAWN_Z_MAX = 0.0, 2.0
        INVERT_TURN_DIRECTION = True
    elif name == "town10_continuation":
        MAP_NAME = "Town10HD_Opt"
        GRAPH = town10_continuation_graph()
        DEFAULT_START_NODE = TOWN10_CONTINUATION_START_NODE
        DEFAULT_GOAL_NODE = TOWN10_CONTINUATION_GOAL_NODE
        FLOOR_Z = 0.0
        FLOOR_PROBE_Z = 1.0
        SAFETY_RAY_Z_OFFSET = 2.5
        SPAWN_Z_MIN, SPAWN_Z_MAX = 0.0, 2.0
        INVERT_TURN_DIRECTION = True
    else:
        raise ValueError(f"unknown scenario {name!r}")
    PRECHECK_RAY_Z_OFFSETS = (
        (1.8, 2.2, 2.5) if name.startswith("town10") else None
    )
    PRECHECK_LATERAL_OFFSETS = (
        (-0.9, 0.0, 0.9) if name.startswith("town10") else None
    )
    PRECHECK_PATH_ORIGIN_S = (
        (0.0,) if name.startswith("town10") else None
    )
    SCENARIO = name
    NODES = {node_id: (node.x, node.y) for node_id, node in GRAPH.nodes.items()}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_metadata(session, ego, image=None, *, with_road=False) -> dict:
    state = nav01b.state_of(ego, session)
    transform = ego.get_transform()
    snapshot = session.world.get_snapshot()
    state.update(
        {
            "heading_rad": round(math.radians(transform.rotation.yaw), 6),
            "snapshot_frame": snapshot.frame,
            "sim_timestamp": snapshot.timestamp.elapsed_seconds,
            "image_frame": None if image is None else image.frame,
            "image_frame_delta": (
                None if image is None else snapshot.frame - image.frame
            ),
        }
    )
    if with_road:
        waypoint = session.world.get_map().get_waypoint(
            transform.location,
            project_to_road=True,
            lane_type=carla.LaneType.Driving,
        )
        state.update(
            {
                "road_id": None if waypoint is None else waypoint.road_id,
                "lane_id": None if waypoint is None else waypoint.lane_id,
                "road_s": None if waypoint is None else round(waypoint.s, 3),
                "lane_width": (
                    None if waypoint is None else round(waypoint.lane_width, 3)
                ),
                "is_junction": None if waypoint is None else waypoint.is_junction,
            }
        )
    return state


def _projection_metadata(points, cumulative, s) -> dict:
    p0 = point_at_s(points, cumulative, s)
    p1 = point_at_s(points, cumulative, min(cumulative[-1], s + 1.0))
    if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) < 1e-3:
        p0, p1 = points[-2], points[-1]
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    return {
        "s": round(s, 3),
        "path_length_m": round(cumulative[-1], 3),
        "point": {"x": round(p0[0], 3), "y": round(p0[1], 3)},
        "point_at_s_plus_1": {"x": round(p1[0], 3), "y": round(p1[1], 3)},
        "tangent": {
            "dx": round((p1[0] - p0[0]) / length, 6),
            "dy": round((p1[1] - p0[1]) / length, 6),
        },
    }


def _ego_footprint(ego) -> dict | None:
    try:
        extent = ego.bounding_box.extent
        return {
            "half_length_m": round(float(extent.x), 3),
            "half_width_m": round(float(extent.y), 3),
            "length_m": round(2.0 * float(extent.x), 3),
            "width_m": round(2.0 * float(extent.y), 3),
            "front_margin_m": round(float(nav01b.FRONT_MARGIN), 3),
        }
    except Exception:
        return None


def _segment_stop_diagnostics(
    *,
    step,
    state,
    target_node_id,
    target_x,
    target_y,
    s,
    cross_track_m,
    points,
    cumulative,
    safety_details,
    min_hit,
    ground,
    monitor,
    monitor_reason,
    ego,
    route_node_ids,
    last_command,
    max_steps=False,
):
    """Build the stop-step snapshot without adding any new stop condition."""

    verdict = forward_safety_verdict(
        min_hit_m=min_hit,
        speed_mps=float(state["speed"]),
        ground_z=ground,
    )
    projection = _projection_metadata(points, cumulative, s)
    projection["cross_track_m"] = round(cross_track_m, 3)
    target = {
        "node_id": target_node_id,
        "x": round(float(target_x), 3),
        "y": round(float(target_y), 3),
        "distance_m": round(
            math.hypot(float(state["x"]) - target_x, float(state["y"]) - target_y),
            3,
        ),
    }
    return build_stop_diagnostics(
        step=step,
        state=state,
        target=target,
        projection=projection,
        safety=safety_details or {},
        monitor=monitor,
        verdict=verdict,
        monitor_reason=monitor_reason,
        max_steps=max_steps,
        ground_inside_ego=bool(
            (safety_details or {}).get("ground_probe_inside_ego", False)
        ),
        footprint=_ego_footprint(ego),
        route={
            "node_ids": list(route_node_ids),
            "length_m": round(cumulative[-1], 3),
        },
        last_command=last_command,
    )


def _capture_round_observation(
    session,
    ego,
    out_dir: Path,
    name_template: str,
    *,
    fov: float,
    camera_role: str,
):
    """Spawn a real front RGB camera for this round and persist one fresh frame.

    The camera is centered on the vehicle's forward axis (yaw 0), so "right in
    the image" still means "right of the vehicle". Only the lens FOV changes
    between rounds: the validated B1 sign is small at the second decision point,
    and a 70-degree lens presents it at a usable size. Both frames are real
    ``sensor.camera.rgb`` output; the exact frame, camera transform and FOV are
    recorded in the evidence.
    """

    camera_bp = session.world.get_blueprint_library().find("sensor.camera.rgb")
    camera_bp.set_attribute("image_size_x", str(CAM_W))
    camera_bp.set_attribute("image_size_y", str(CAM_H))
    camera_bp.set_attribute("fov", str(fov))
    camera_bp.set_attribute("sensor_tick", "0.0")
    camera_bp.set_attribute("role_name", camera_role)
    camera_tf = carla.Transform(
        carla.Location(x=CAM_OFFSET[0], y=CAM_OFFSET[1], z=CAM_OFFSET[2]),
        carla.Rotation(pitch=CAM_PITCH, yaw=0.0),
    )
    camera = session.world.spawn_actor(camera_bp, camera_tf, attach_to=ego)
    session.actors.append(camera)
    latest = nav01b.LatestImage()
    camera.listen(latest)
    try:
        session.tick(25)
        image = None
        for _ in range(30):
            snapshot = session.world.get_snapshot()
            candidate = latest.image
            if candidate is not None and 0 <= snapshot.frame - candidate.frame <= 2:
                image = candidate
                break
            session.tick()
        if image is None:
            raise RuntimeError("camera produced no fresh frame within 30 ticks")
        if image.width != CAM_W or image.height != CAM_H:
            raise RuntimeError(
                f"camera frame is {image.width}x{image.height}, expected {CAM_W}x{CAM_H}"
            )
        expected = image.width * image.height * 4
        if len(image.raw_data) != expected:
            raise RuntimeError(
                f"camera buffer is {len(image.raw_data)} bytes, expected {expected}"
            )
        state = _state_metadata(session, ego, image, with_road=True)
        if state["image_frame_delta"] > 2:
            raise RuntimeError(
                f"stale camera frame: image.frame={image.frame}, "
                f"world.frame={state['snapshot_frame']}"
            )
        frame = CameraFrame.from_bgra(
            frame_id=image.frame,
            timestamp=image.timestamp,
            width=image.width,
            height=image.height,
            raw_bgra=bytes(image.raw_data),
            sim_frame=state["snapshot_frame"],
        )
        image_path = str(out_dir / (name_template % image.frame))
        write_rgb_png(image_path, frame.rgb, frame.width, frame.height)
        image_sha = observe01c.sha256_file(image_path)
        image_size = os.path.getsize(image_path)
        camera_meta = {
            "actor_id": camera.id,
            "role_name": camera_role,
            "fov": fov,
            "width": CAM_W,
            "height": CAM_H,
            "transform": {
                "x": camera_tf.location.x,
                "y": camera_tf.location.y,
                "z": camera_tf.location.z,
                "pitch": camera_tf.rotation.pitch,
                "yaw": camera_tf.rotation.yaw,
            },
        }
        return frame, state, image_path, image_sha, image_size, camera_meta
    finally:
        camera.stop()
        camera.destroy()
        if camera in session.actors:
            session.actors.remove(camera)


def _capture_final_photo(session, out_dir, *, fov=90.0):
    """Static post-run camera at the B1 aisle looking west at the parked car."""

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    library = session.world.get_blueprint_library()
    bp = library.find("sensor.camera.rgb")
    bp.set_attribute("image_size_x", str(CAM_W))
    bp.set_attribute("image_size_y", str(CAM_H))
    bp.set_attribute("fov", str(fov))
    bp.set_attribute("sensor_tick", "0.0")
    bp.set_attribute("role_name", "demo_final_photo")
    transform = carla.Transform(
        carla.Location(x=-4.0, y=-21.0, z=7.2),
        carla.Rotation(pitch=0.0, yaw=180.0),
    )
    camera = session.world.spawn_actor(bp, transform)
    latest = nav01b.LatestImage()
    camera.listen(latest)
    try:
        session.tick(25)
        image = None
        for _ in range(30):
            snapshot = session.world.get_snapshot()
            candidate = latest.image
            if candidate is not None and 0 <= snapshot.frame - candidate.frame <= 2:
                image = candidate
                break
            session.tick()
        if image is None:
            raise RuntimeError("final photo camera produced no fresh frame")
        path = out / f"final_parking_{image.frame}.png"
        image.save_to_disk(str(path))
        return {
            "path": str(path),
            "frame": image.frame,
            "sha256": observe01c.sha256_file(path),
            "size_bytes": os.path.getsize(path),
            "fov": float(fov),
            "transform": {
                "x": transform.location.x,
                "y": transform.location.y,
                "z": transform.location.z,
                "pitch": transform.rotation.pitch,
                "yaw": transform.rotation.yaw,
            },
            "note": (
                "static post-run camera at the B1 aisle looking west at the "
                "parked car in bay 03; not a moving-camera frame"
            ),
        }
    finally:
        camera.stop()
        camera.destroy()


def _prompt_for(
    state: dict,
    target: str,
    target_kind: str,
    intent_id: str,
    instruction: str,
    target_note: str,
    history_context: str = "",
    route_context: str = "",
) -> str:
    state_text = (
        f"当前车辆状态（来自 CARLA 本轮仿真）：x={state['x']:.3f} m，"
        f"y={state['y']:.3f} m，yaw={state['yaw']:.3f}°"
        f"（{state['heading_rad']:.6f} rad），速度={state['speed']:.3f} m/s。"
    )
    history_block = ""
    if history_context:
        if type(history_context) is not str:
            raise ValueError("history_context must be a str")
        history_block = (
            "\n短期记忆（前序轮次摘要，仅用于保持任务连续性；"
            "不是当前图像证据，也不能证明已经到达）：\n"
            + history_context
        )
    nav_prompt = build_nav_prompt(
        Variant.TARGET_DIRECTION,
        target=target,
        intent_id=intent_id,
        target_kind=target_kind,
        require_identity=True,
        require_evidence=True,
        target_note=target_note,
        clarify_decision_fields=True,
        route_context=route_context,
    )
    return (
        f"用户导航指令：{instruction}\n{state_text}{history_block}\n\n{nav_prompt}"
    )


def _route_facts_for_prompt(
    *,
    pose,
    target: str,
    expected_node_id,
    goal_node_id: str,
    args,
    excluded_nodes,
):
    """Build the advisory route block for one prompt from the real pose."""

    try:
        candidate_facts = route_candidates(
            GRAPH,
            pose,
            goal_node_id,
            expected_node_id=expected_node_id,
            max_node_distance_m=MAX_NODE_DISTANCE_M,
            straight_tolerance_deg=STRAIGHT_TOLERANCE_DEG,
            turn_limit_deg=TURN_LIMIT_DEG,
            invert_turn_direction=INVERT_TURN_DIRECTION,
            excluded_nodes=excluded_nodes,
        )
        if candidate_facts.ok and candidate_facts.candidates:
            facts = build_route_facts_from_candidates(
                node_id=candidate_facts.matched_node_id,
                matched_node_distance_m=candidate_facts.matched_node_distance_m,
                pose=pose,
                candidates=candidate_facts.candidates,
                goal_node_id=goal_node_id,
            )
            return facts, format_route_facts(facts, target=target)
        return candidate_facts.to_metadata(), ""
    except Exception as exc:  # prompt facts are advisory context only
        return {"error": f"{type(exc).__name__}: {exc}"}, ""


def _model_request_evidence(
    calls,
    image_sha: str,
    *,
    inference_started: str,
    inference_finished: str,
    planner_client,
) -> dict:
    """Build the existing request evidence, including the final model prompt."""

    request = observe01c.request_evidence(calls, image_sha)
    request["inference_started_utc"] = inference_started
    request["inference_finished_utc"] = inference_finished
    if planner_client is not None:
        request["model_path"] = "kernel_planner_bridge"
        exchange = planner_client.last_exchange
        if exchange is not None:
            # The actual HTTP request happens in the bridge process, so the
            # in-process recorder sees no call. The bridge hashes the exact
            # image file it reads and the Host forwards that hash; it is the
            # same evidence the recorder would have produced.
            bridge_image_sha = exchange.output.get("image_sha256")
            request["request_count"] = 1
            request["request_evidence_source"] = "kernel_planner_bridge"
            request["image_path"] = exchange.output.get("image_path")
            request["image_sha256_in_request"] = bridge_image_sha
            request["image_sha256_matches_frame"] = (
                bridge_image_sha == image_sha
            )
            request["payload_prompt_sha256"] = exchange.output.get(
                "prompt_sha256"
            )
            server_response = exchange.output.get("server_response")
            if isinstance(server_response, dict):
                request["server_response"] = server_response
                request["server_response_id"] = server_response.get(
                    "server_response_id"
                )
                request["response_model"] = server_response.get("response_model")
                request["finish_reason"] = server_response.get("finish_reason")
                request["usage"] = server_response.get("usage")
            request["planner_request_id"] = exchange.planner_request_id
            request["planner_artifact_id"] = exchange.planning_artifact_id
            request["planner_context_revision"] = exchange.context_revision
            request["raw_model_output_sha256"] = exchange.output.get(
                "raw_output_sha256"
            )
            request["bridge_latency_ms"] = exchange.output.get("bridge_latency_ms")
            request["final_prompt"] = exchange.output.get("prompt")
            request["final_prompt_sha256"] = exchange.output.get("prompt_sha256")
            request["context_selection"] = exchange.output.get("context_selection")
    return request


def _safe_stop_for_reobservation(session, ego) -> dict:
    """Bring the vehicle to a real stop before taking a new observation."""

    before = _state_metadata(session, ego, with_road=True)
    session.brake_to_stop(ego, max_ticks=60)
    after = _state_metadata(session, ego, with_road=True)
    stopped = float(after["speed"]) <= 0.1
    return {
        "before_speed_mps": before["speed"],
        "after_speed_mps": after["speed"],
        "stopped": stopped,
        "max_ticks": 60,
    }


def _attempt_visual_recovery(
    *,
    machine: VisualRecoveryMachine,
    session,
    ego,
    out_dir,
    args,
    host_client,
    host_planner: bool,
    host_session_id,
    host_context_revision,
    task_memory,
    round_index: int,
    target: str,
    route_goal_node_id: str,
    expected_node_id,
    excluded_nodes,
    initial_outcome,
    initial_frame,
    initial_state: dict,
    initial_image_path: str,
    initial_image_sha: str,
    initial_image_size: int,
    initial_observation,
    initial_request: dict,
    initial_planner_client,
    initial_intent_id: str,
    last_verified_identity,
) -> dict:
    """Stop, re-observe and re-infer until the budget or the verification ends.

    Every retry runs the original ``generate_and_decide`` chain. This helper
    never arbitrates a route and never asks for execution; the caller only
    reaches those steps after the returned outcome is a verified success.
    """

    evidence: list[dict] = []
    initial_kind = classify_visual_uncertainty(
        initial_outcome,
        expected_identity=target,
        previously_confirmed_identity=last_verified_identity,
    )
    initial_exchange = None
    if initial_planner_client is not None:
        exchange = initial_planner_client.last_exchange
        if exchange is not None:
            initial_exchange = exchange.to_metadata()
    evidence.append(
        {
            "attempt": 0,
            "phase": "initial_failure",
            "uncertainty_type": initial_kind,
            "observation": {
                "frame": initial_frame.to_metadata(),
                "state": initial_state,
                "image_path": initial_image_path,
                "image_sha256": initial_image_sha,
                "image_size_bytes": initial_image_size,
                "prompt": initial_observation.prompt,
            },
            "context_revision": host_context_revision,
            "request": initial_request,
            "planner": initial_exchange,
            "decision": initial_outcome.to_metadata(),
        }
    )

    current_outcome = initial_outcome
    current_kind = initial_kind
    current_frame = initial_frame
    current_state = initial_state
    current_image_path = initial_image_path
    current_image_sha = initial_image_sha
    current_image_size = initial_image_size
    current_observation = initial_observation
    current_intent_id = initial_intent_id
    current_request = initial_request
    current_planner_client = initial_planner_client
    current_context_revision = host_context_revision
    inference_started = initial_request.get("inference_started_utc")
    inference_finished = initial_request.get("inference_finished_utc")
    inference_wall_s = 0.0

    while True:
        action = machine.on_failure(
            current_kind,
            reason=(
                "initial visual rejection"
                if current_kind is not None
                else "non-recoverable failure"
            ),
        )
        if action != VisualRecoveryAction.REQUEST_REOBSERVATION:
            return {
                "recovered": False,
                "outcome": current_outcome,
                "frame": current_frame,
                "state": current_state,
                "image_path": current_image_path,
                "image_sha": current_image_sha,
                "image_size": current_image_size,
                "observation": current_observation,
                "intent_id": current_intent_id,
                "request": current_request,
                "planner_client": current_planner_client,
                "context_revision": current_context_revision,
                "inference_started_utc": inference_started,
                "inference_finished_utc": inference_finished,
                "inference_wall_s": inference_wall_s,
                "recovery": {
                    **machine.to_metadata(),
                    "attempts": evidence,
                    "recovered": False,
                },
            }

        attempt_number = machine.attempt_count
        try:
            stop_report = _safe_stop_for_reobservation(session, ego)
        except Exception as exc:
            machine.refuse(f"safe stop failed: {type(exc).__name__}: {exc}")
            break
        if not stop_report["stopped"]:
            machine.refuse(
                "vehicle did not reach a stopped state before re-observation: "
                f"speed={stop_report['after_speed_mps']} m/s"
            )
            break

        # Record the rejected judgement in STM before the retry prompt is built,
        # so the new prompt sees the failure as history, not as current evidence.
        task_memory.record_carla_round(
            round_index=round_index,
            intent_id=current_intent_id,
            action=None,
            target=None,
            visual_decision=current_outcome.decision,
            directive=None,
            outcome=RoundOutcome.REJECTED,
            task_target=target,
            execution=None,
            error=(
                f"{current_outcome.status}: {current_outcome.error_type}: "
                f"{current_outcome.error_message}"
            ),
        )

        try:
            (
                new_frame,
                new_state,
                new_image_path,
                new_image_sha,
                new_image_size,
                _camera_meta,
            ) = _capture_round_observation(
                session,
                ego,
                out_dir,
                (
                    f"round_{round_index:02d}_vr{attempt_number:02d}"
                    "_frame_%06d.png"
                ),
                fov=70.0,
                camera_role=f"{CAM_ROLE}_r{round_index}_vr{attempt_number}",
            )
            new_frame_guard = require_new_observation(
                previous_frame_id=current_frame.frame_id,
                previous_image_sha256=current_image_sha,
                new_frame_id=new_frame.frame_id,
                new_image_sha256=new_image_sha,
            )
        except RecoveryRefused as exc:
            machine.refuse(str(exc))
            break
        except Exception as exc:
            machine.refuse(
                f"new observation failed: {type(exc).__name__}: {exc}"
            )
            break

        new_pose = VehiclePose(
            x=new_state["x"],
            y=new_state["y"],
            heading=math.radians(new_state["yaw"]),
        )
        note = reobservation_note(current_kind, attempt_number)
        target_note = args.target_note.format(target=target) + "\n" + note
        history_context = task_memory.render_compact_context(max_chars=2400)
        route_facts, route_context = _route_facts_for_prompt(
            pose=new_pose,
            target=target,
            expected_node_id=expected_node_id,
            goal_node_id=route_goal_node_id,
            args=args,
            excluded_nodes=excluded_nodes,
        )
        recovery_intent_id = f"{initial_intent_id}-vr{attempt_number}"
        prompt = _prompt_for(
            new_state,
            target,
            args.target_kind,
            recovery_intent_id,
            args.instruction,
            target_note,
            history_context=history_context,
            route_context=route_context,
        )
        new_observation = CarlaVisualObservation(
            frame=new_frame,
            image_path=new_image_path,
            image_sha256=new_image_sha,
            image_size_bytes=new_image_size,
            pose=new_pose,
            instruction=args.instruction,
            prompt=prompt,
        )

        planner_client = None
        new_outcome = None
        request_record = None
        started_utc = utc_now()
        started_monotonic = time.monotonic()
        calls, restore_opener = observe01c.install_request_recorder()
        try:
            if host_planner:
                planner_client = HostPlannerModelClient(
                    host_client,
                    session_id=host_session_id,
                    context_revision=current_context_revision,
                    request_id_prefix=(
                        f"cap08b-vr-r{round_index}-a{attempt_number}"
                    ),
                    domain={
                        "capability": "planner.plan",
                        "parking": PARKING_CONTEXT,
                        "round": round_index,
                        "intent_id": recovery_intent_id,
                        "trigger": "visual_uncertainty",
                        "uncertainty_type": current_kind,
                        "attempt": attempt_number,
                        "previous_intent_id": current_intent_id,
                        "previous_frame_id": current_frame.frame_id,
                        "previous_image_sha256": current_image_sha,
                        "new_frame_id": new_frame.frame_id,
                        "new_image_sha256": new_image_sha,
                        "previous_error_type": current_outcome.error_type,
                        "previous_error_message": current_outcome.error_message,
                        "target": target,
                        "target_kind": args.target_kind,
                        "pose": {
                            "x": new_state["x"],
                            "y": new_state["y"],
                            "yaw": new_state["yaw"],
                        },
                        "frame_id": new_frame.frame_id,
                        "image_sha256": new_image_sha,
                        "route_goal_node_id": route_goal_node_id,
                    },
                )
                model = planner_client
            else:
                model = ServerImageModelClient(
                    backend=ZDTaichuServerBackend(
                        max_new_tokens=max(4096, args.max_new_tokens),
                        timeout=args.timeout,
                        temperature=0.0,
                        enable_thinking=args.enable_thinking,
                        stop=None if args.enable_thinking else ["</think>"],
                    )
                )
            new_outcome = generate_and_decide(
                model,
                new_observation,
                expected_identity=target,
                intent_id=recovery_intent_id,
            )
        except Exception as exc:  # model construction/transport boundary
            new_outcome = None
            planner_error = f"{type(exc).__name__}: {exc}"
        else:
            planner_error = None
        finally:
            finished_utc = utc_now()
            wall_s = time.monotonic() - started_monotonic
            if restore_opener is not None:
                restore_opener()
                restore_opener = None

        revision_ok = False
        if planner_client is not None:
            updated_revision = planner_client.context_revision_after
            try:
                current_context_revision = ensure_context_revision_advanced(
                    current_context_revision, updated_revision
                )
                revision_ok = True
            except RecoveryRefused as exc:
                planner_error = str(exc)
            request_record = _model_request_evidence(
                calls,
                new_image_sha,
                inference_started=started_utc,
                inference_finished=finished_utc,
                planner_client=planner_client,
            )
        else:
            request_record = _model_request_evidence(
                calls,
                new_image_sha,
                inference_started=started_utc,
                inference_finished=finished_utc,
                planner_client=None,
            )
            revision_ok = True

        exchange_meta = None
        if planner_client is not None and planner_client.last_exchange is not None:
            exchange_meta = planner_client.last_exchange.to_metadata()
        evidence.append(
            {
                "attempt": attempt_number,
                "phase": "reobservation",
                "uncertainty_type": current_kind,
                "recovery_note": note,
                "stop": stop_report,
                "new_frame": new_frame_guard,
                "observation": {
                    "camera": _camera_meta,
                    "frame": new_frame.to_metadata(),
                    "state": new_state,
                    "image_path": new_image_path,
                    "image_sha256": new_image_sha,
                    "image_size_bytes": new_image_size,
                    "prompt": prompt,
                    "route_facts": route_facts,
                },
                "context_revision": current_context_revision,
                "revision_advanced": revision_ok,
                "request": request_record,
                "planner": exchange_meta,
                "decision": (
                    None if new_outcome is None else new_outcome.to_metadata()
                ),
                "planner_error": planner_error,
            }
        )

        if new_outcome is None:
            machine.refuse(planner_error or "recovery model call failed")
            break
        if not revision_ok:
            machine.refuse(planner_error or "context revision did not advance")
            break
        if new_outcome.status == SUCCESS:
            machine.on_success()
            return {
                "recovered": True,
                "outcome": new_outcome,
                "frame": new_frame,
                "state": new_state,
                "image_path": new_image_path,
                "image_sha": new_image_sha,
                "image_size": new_image_size,
                "observation": new_observation,
                "intent_id": recovery_intent_id,
                "request": request_record,
                "planner_client": planner_client,
                "context_revision": current_context_revision,
                "inference_started_utc": started_utc,
                "inference_finished_utc": finished_utc,
                "inference_wall_s": wall_s,
                "recovery": {
                    **machine.to_metadata(),
                    "attempts": evidence,
                    "recovered": True,
                },
                "target_note": target_note,
                "route_facts": route_facts,
                "route_context": route_context,
            }

        # The retry failed too. Classify it for the next bounded attempt; a
        # structural/transport failure returns None and is refused next loop.
        current_outcome = new_outcome
        current_frame = new_frame
        current_state = new_state
        current_image_path = new_image_path
        current_image_sha = new_image_sha
        current_image_size = new_image_size
        current_observation = new_observation
        current_intent_id = recovery_intent_id
        current_request = request_record
        current_planner_client = planner_client
        current_kind = classify_visual_uncertainty(
            new_outcome,
            expected_identity=target,
            previously_confirmed_identity=last_verified_identity,
        )
        inference_started = started_utc
        inference_finished = finished_utc
        inference_wall_s = wall_s

    # Safety stop / new-frame / context guards refused further recovery.
    return {
        "recovered": False,
        "outcome": current_outcome,
        "frame": current_frame,
        "state": current_state,
        "image_path": current_image_path,
        "image_sha": current_image_sha,
        "image_size": current_image_size,
        "observation": current_observation,
        "intent_id": current_intent_id,
        "request": current_request,
        "planner_client": current_planner_client,
        "context_revision": current_context_revision,
        "inference_started_utc": inference_started,
        "inference_finished_utc": inference_finished,
        "inference_wall_s": inference_wall_s,
        "recovery": {
            **machine.to_metadata(),
            "attempts": evidence,
            "recovered": False,
        },
    }


def _stm_execution_feedback(execution: dict | None) -> dict | None:
    """Summarise one real segment result for the short-term memory ledger."""

    if not isinstance(execution, dict):
        return None
    kernel = execution.get("kernel") or {}
    response = kernel.get("response") or {}
    post = execution.get("post_state") or {}
    feedback = {
        "executed": execution.get("executed"),
        "target_node_id": execution.get("target_node_id"),
        "moved_m": execution.get("moved_m"),
        "stop_reason": execution.get("stop_reason"),
        "segment_success": execution.get("segment_success"),
        "selected_edge": execution.get("model_selected_edge"),
        "route_node_ids": execution.get("route_node_ids"),
        "kernel_execution_status": response.get("execution_status"),
        "post_state": (
            None
            if not isinstance(post, dict)
            else {
                "x": post.get("x"),
                "y": post.get("y"),
                "yaw": post.get("yaw"),
                "speed": post.get("speed"),
            }
        ),
    }
    redecision = execution.get("redecision")
    if isinstance(redecision, dict):
        feedback["redecision"] = dict(redecision)
    return feedback


def _stm_outcome_for_execution(execution: dict | None) -> str:
    if not isinstance(execution, dict):
        return RoundOutcome.FAILED_BEFORE_EXECUTION
    if execution.get("segment_success") is True:
        return RoundOutcome.SOFTWARE_SUCCEEDED
    if execution.get("executed") is not True:
        return RoundOutcome.FAILED_BEFORE_EXECUTION
    return RoundOutcome.EXECUTION_FAILED


def _record_stm_round(
    *,
    task_memory: NavigationTaskMemory,
    round_result: dict,
    round_index: int,
    task_target: str,
    final_outcome,
    execution: dict | None,
    outcome: str,
    error: str | None,
) -> dict:
    """Record one round in the caller-owned STM and keep its evidence."""

    feedback = _stm_execution_feedback(execution)
    intent = None if final_outcome is None else final_outcome.intent
    target_xy = None
    if intent is not None:
        target_xy = {"x": intent.target.x, "y": intent.target.y}
    record = task_memory.record_carla_round(
        round_index=round_index,
        intent_id=None if intent is None else intent.intent_id,
        action=None if intent is None else intent.action,
        target=target_xy,
        visual_decision=None if final_outcome is None else final_outcome.decision,
        directive=None if final_outcome is None else final_outcome.directive,
        outcome=outcome,
        task_target=task_target,
        execution=feedback,
        error=error,
    )
    payload = {
        "round_index": record.round_index,
        "outcome": record.outcome,
        "error": record.error,
        "intent_id": record.intent_id,
        "action": record.action,
        "task_target": task_target,
        "execution": feedback,
    }
    round_result["stm"]["record"] = payload
    round_result["stm"]["records_after"] = len(task_memory.records)
    context_after = task_memory.render_compact_context(max_chars=2400)
    round_result["stm"]["context_after"] = context_after
    round_result["stm"]["context_after_sha256"] = observe01c.sha256_bytes(
        context_after.encode("utf-8")
    )
    round_result["stm"]["context_after_full_sha256"] = observe01c.sha256_bytes(
        task_memory.render_context().encode("utf-8")
    )
    return payload


def _stable_parking_stop(
    session, ego, ticks: int = PARKING_STOP_STABLE_TICKS
) -> dict:
    """Hold the brake and sample the real post-run state for stability."""

    poses = []
    speeds = []
    last = None
    for _ in range(ticks):
        ego.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0, steer=0.0))
        session.tick()
        last = _state_metadata(session, ego)
        poses.append((last["x"], last["y"]))
        speeds.append(last["speed"])
    final_state = _state_metadata(session, ego, with_road=True)
    drift = 0.0
    if poses:
        drift = max(
            math.hypot(x - poses[0][0], y - poses[0][1]) for x, y in poses
        )
    max_speed = max(speeds) if speeds else final_state["speed"]
    return {
        "samples": ticks,
        "max_speed_mps": round(max_speed, 4),
        "position_drift_m": round(drift, 4),
        "stable": max_speed < 0.05 and drift <= 0.02,
        "final_state": final_state,
    }


def _align_parking_pose(
    session,
    ego,
    target_x: float,
    target_y: float,
    obstacles,
    args,
) -> dict:
    """Short reverse-align then forward-to-slot correction.

    The 3.56 m forward arc reaches the bay with a few degrees of residual
    heading error at this vehicle's low-speed steering response.  A short
    reverse arc rotates the nose to west while moving 0.4-1.2 m east; a short
    forward straight then returns the centre to the slot.  Both phases are
    bounded, use the same ray/floor/static-clearance gates, and stop on any
    new collision.
    """

    target_heading = PARKING_SLOT_HEADING_RAD
    phase_records = []
    phases = {}
    baseline = _collision_count()
    pre_state = _state_metadata(session, ego, with_road=True)
    reverse_speed_cap = 0.16
    forward_speed_cap = 0.14

    def _heading_error_deg(state) -> float:
        return math.degrees(
            (math.radians(state["yaw"]) - target_heading + math.pi)
            % (2.0 * math.pi)
            - math.pi
        )

    def _reverse_path(state, length_m=3.0):
        rx = state["x"] - length_m * math.cos(math.radians(state["yaw"]))
        ry = state["y"] - length_m * math.sin(math.radians(state["yaw"]))
        return [(state["x"], state["y"]), (rx, ry)]

    def _forward_path(state, length_m=3.0):
        fx = state["x"] + length_m * math.cos(math.radians(state["yaw"]))
        fy = state["y"] + length_m * math.sin(math.radians(state["yaw"]))
        return [(state["x"], state["y"]), (fx, fy)]

    # Phase 1: reverse with a proportional heading-to-west controller.
    phase1 = {"phase": "reverse_align", "records": [], "stop_reason": None}
    start = _state_metadata(session, ego)
    traveled = 0.0
    for step in range(400):
        state = _state_metadata(session, ego)
        traveled = math.hypot(state["x"] - start["x"], state["y"] - start["y"])
        herr_rad = math.radians(_heading_error_deg(state))
        path = _reverse_path(state)
        safety_details = {}
        blocked, min_hit, ground = nav01b.safety_check(
            session,
            ego,
            path,
            cumulative_lengths(path),
            0.0,
            floor_probe_z=FLOOR_PROBE_Z,
            ray_z_offset=SAFETY_RAY_Z_OFFSET,
            reverse=True,
            stop_distance_m=PARKING_STOP_DISTANCE_M,
            details_out=safety_details,
        )
        clearance = footprint_clearance(
            state["x"],
            state["y"],
            math.radians(state["yaw"]),
            PARKING_FOOTPRINT,
            obstacles,
        )
        if _collision_count() > baseline:
            phase1["stop_reason"] = "collision"
            break
        if blocked:
            phase1["stop_reason"] = "obstacle"
            break
        if (
            clearance["min_clearance_m"] is not None
            and clearance["min_clearance_m"] < PARKING_STATIC_CLEARANCE_M
        ):
            phase1["stop_reason"] = "clearance_margin"
            break
        if abs(_heading_error_deg(state)) <= 1.5:
            phase1["stop_reason"] = "aligned"
            break
        if traveled >= 2.4:
            phase1["stop_reason"] = "distance"
            break
        if state["t"] - start["t"] > 30.0:
            phase1["stop_reason"] = "timeout"
            break
        steer = max(-0.6, min(0.6, 3.0 * herr_rad))
        # The charger's automatic gearbox does not engage reverse from a
        # braked forward state at 0.22 throttle (measured: speed stayed 0);
        # 0.45 engages it. The cap is still enforced by braking.
        if state["speed"] < reverse_speed_cap:
            throttle, brake = 0.45, 0.0
        else:
            throttle, brake = 0.0, 0.25
        control = carla.VehicleControl(
            throttle=throttle, steer=steer, brake=brake, reverse=True
        )
        ego.apply_control(control)
        record = {
            "phase": "reverse_align",
            "step": step,
            "t": state["t"],
            "x": state["x"],
            "y": state["y"],
            "yaw": state["yaw"],
            "speed": state["speed"],
            "steer": round(steer, 3),
            "throttle": throttle,
            "brake": brake,
            "reverse": True,
            "heading_error_deg": round(_heading_error_deg(state), 3),
            "traveled_m": round(traveled, 3),
            "static_clearance_m": clearance["min_clearance_m"],
            "safety_min_hit_m": None if min_hit is None else round(min_hit, 3),
        }
        phase1["records"].append(record)
        phase_records.append(record)
        session.tick()
    ego.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0, steer=0.0))
    for _ in range(80):
        session.tick()
        if _state_metadata(session, ego)["speed"] < 0.03:
            break
    phase1["post_state"] = _state_metadata(session, ego)
    phases["reverse_align"] = phase1

    # Phase 2: forward straight to the slot centre at the aligned heading.
    phase2 = {"phase": "forward_to_slot", "records": [], "stop_reason": None}
    start = _state_metadata(session, ego)
    traveled = 0.0
    for step in range(700):
        state = _state_metadata(session, ego)
        traveled = math.hypot(state["x"] - start["x"], state["y"] - start["y"])
        herr_rad = math.radians(_heading_error_deg(state))
        distance = math.hypot(state["x"] - target_x, state["y"] - target_y)
        path = _forward_path(state)
        safety_details = {}
        blocked, min_hit, ground = nav01b.safety_check(
            session,
            ego,
            path,
            cumulative_lengths(path),
            0.0,
            floor_probe_z=FLOOR_PROBE_Z,
            ray_z_offset=SAFETY_RAY_Z_OFFSET,
            stop_distance_m=PARKING_STOP_DISTANCE_M,
            details_out=safety_details,
        )
        clearance = footprint_clearance(
            state["x"],
            state["y"],
            math.radians(state["yaw"]),
            PARKING_FOOTPRINT,
            obstacles,
        )
        if _collision_count() > baseline:
            phase2["stop_reason"] = "collision"
            break
        if blocked:
            phase2["stop_reason"] = "obstacle"
            break
        if (
            clearance["min_clearance_m"] is not None
            and clearance["min_clearance_m"] < PARKING_STATIC_CLEARANCE_M
        ):
            phase2["stop_reason"] = "clearance_margin"
            break
        if distance <= 0.12 and abs(_heading_error_deg(state)) <= 3.0:
            phase2["stop_reason"] = "aligned"
            break
        if state["x"] <= target_x + 0.02:
            phase2["stop_reason"] = "slot_x_reached"
            break
        if traveled >= 3.2:
            phase2["stop_reason"] = "distance"
            break
        if state["t"] - start["t"] > 40.0:
            phase2["stop_reason"] = "timeout"
            break
        # Forward motion responds to steer with the opposite yaw sign from
        # reverse: a positive heading error needs a right (negative) steer.
        steer = max(-0.5, min(0.5, -2.0 * herr_rad))
        if state["speed"] < forward_speed_cap:
            throttle, brake = 0.45, 0.0
        else:
            throttle, brake = 0.0, 0.25
        control = carla.VehicleControl(
            throttle=throttle, steer=steer, brake=brake, reverse=False
        )
        ego.apply_control(control)
        record = {
            "phase": "forward_to_slot",
            "step": step,
            "t": state["t"],
            "x": state["x"],
            "y": state["y"],
            "yaw": state["yaw"],
            "speed": state["speed"],
            "steer": round(steer, 3),
            "throttle": throttle,
            "brake": brake,
            "reverse": False,
            "heading_error_deg": round(_heading_error_deg(state), 3),
            "distance_to_slot_m": round(distance, 3),
            "traveled_m": round(traveled, 3),
            "static_clearance_m": clearance["min_clearance_m"],
            "safety_min_hit_m": None if min_hit is None else round(min_hit, 3),
        }
        phase2["records"].append(record)
        phase_records.append(record)
        session.tick()
    ego.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0, steer=0.0))
    for _ in range(80):
        session.tick()
        if _state_metadata(session, ego)["speed"] < 0.03:
            break
    phase2["post_state"] = _state_metadata(session, ego)
    phases["forward_to_slot"] = phase2

    post_state = _state_metadata(session, ego, with_road=True)
    distance = math.hypot(post_state["x"] - target_x, post_state["y"] - target_y)
    heading_error = abs(
        math.degrees(
            (math.radians(post_state["yaw"]) - target_heading + math.pi)
            % (2.0 * math.pi)
            - math.pi
        )
    )
    success = (
        distance <= 0.25
        and heading_error <= 5.0
        and post_state["speed"] < 0.05
        and _collision_count() == baseline
    )
    return {
        "success": success,
        "pre_state": pre_state,
        "post_state": post_state,
        "distance_to_slot_m": round(distance, 3),
        "heading_error_deg": round(heading_error, 3),
        "phases": phases,
        "records": phase_records,
        "collision_count": _collision_count() - baseline,
    }


def _drive_parking_segment(
    session,
    ego,
    arbitration,
    args,
    round_index: int,
    decision_direction: str,
) -> dict:
    """Execute the final bay-03 arc with the shared low-speed parking law.

    This is the same Kernel-authorized execution path as an aisle segment; only
    the controller speed/lookahead and the stop rule change.  Every step still
    runs the existing forward-ray/floor safety gate, and the measured 07A
    obstacle points provide a 0.2 m footprint-clearance guard so a cut-inside
    arc is stopped instead of touching the north pillar.
    """

    selected_nodes, selected_points = execution_route(arbitration, GRAPH)
    route_node_ids = list(selected_nodes)
    route_points = list(selected_points)
    cumulative = cumulative_lengths(route_points)
    target_node_id = route_node_ids[-1]
    target_x, target_y = NODES[target_node_id]
    pre_state = _state_metadata(session, ego, with_road=True)
    start_s, _, _, pre_cross = project_to_path(
        route_points,
        cumulative,
        pre_state["x"],
        pre_state["y"],
        0.0,
        window_m=PROJECTION_WINDOW_M,
    )
    obstacles = _all_parking_obstacles()
    parking_origins, parking_stop = _parking_precheck_plan(
        route_node_ids, target_node_id, start_s
    )
    initial_details = {}
    initial_blocked, initial_min, initial_ground = nav01b.safety_check(
        session,
        ego,
        route_points,
        cumulative,
        start_s,
        floor_probe_z=FLOOR_PROBE_Z,
        ray_z_offset=SAFETY_RAY_Z_OFFSET,
        path_origin_s=parking_origins,
        stop_distance_m=parking_stop,
        min_probe_distance_m=float(args.safety_probe_distance),
        details_out=initial_details,
    )
    initial_clearance = footprint_clearance(
        pre_state["x"],
        pre_state["y"],
        math.radians(pre_state["yaw"]),
        PARKING_FOOTPRINT,
        obstacles,
    )
    result = {
        "target_node_id": target_node_id,
        "target_index": len(route_node_ids) - 1,
        "target_xy": {"x": target_x, "y": target_y},
        "model_selected_edge": list(arbitration.selected_edge),
        "route_node_ids": route_node_ids,
        "route_points": [list(point) for point in route_points],
        "pre_state": pre_state,
        "pre_cross_track_m": round(pre_cross, 3),
        "initial_safety": {
            "blocked": initial_blocked,
            "min_hit_m": None if initial_min is None else round(initial_min, 3),
            "ground_z": initial_ground,
        },
        "initial_safety_details": initial_details,
        "initial_static_clearance": initial_clearance,
        "static_obstacle_count": len(obstacles),
        "parking_phase": True,
        "records": [],
        "steps": 0,
        "stop_reason": None,
        "model_control_note": (
            "the model selected the route; the final bay arc was executed by "
            "the shared low-speed parking controller inside the Kernel-invoked "
            "CARLA execution, with the forward-ray/floor gate and the 07A "
            "measured-obstacle clearance guard active on every step"
        ),
    }
    if initial_blocked:
        result["stop_reason"] = "safety_precheck"
        result["post_state"] = pre_state
        result["stopped"] = pre_state["speed"] < 0.05
        result["distance_to_target_m"] = round(
            math.hypot(pre_state["x"] - target_x, pre_state["y"] - target_y), 3
        )
        result["segment_success"] = False
        return result
    if (
        initial_clearance["min_clearance_m"] is not None
        and initial_clearance["min_clearance_m"] < PARKING_STATIC_CLEARANCE_M
    ):
        result["stop_reason"] = "clearance_preecheck"
        result["post_state"] = pre_state
        result["stopped"] = pre_state["speed"] < 0.05
        result["distance_to_target_m"] = round(
            math.hypot(pre_state["x"] - target_x, pre_state["y"] - target_y), 3
        )
        result["segment_success"] = False
        return result

    speed_cap = float(getattr(args, "parking_speed_cap", 0.35))
    requested_sim_seconds = float(getattr(args, "max_parking_sim_seconds", 90.0))
    requested_steps = int(getattr(args, "max_parking_steps", 1400))
    budget = parking_execution_budget(
        cumulative[-1],
        speed_cap,
        FIXED_DT,
        requested_steps,
        requested_sim_seconds,
    )
    max_sim_seconds = budget["sim_seconds"]
    max_steps = budget["steps"]
    result["execution_budget"] = budget
    baseline_collisions = _collision_count()
    start_t = pre_state["t"]
    steps = 0
    reason = None
    last_state = pre_state
    last_s = start_s
    last_cross = pre_cross
    last_clearance = initial_clearance
    last_min_hit = initial_min
    last_ground = initial_ground
    last_details = initial_details
    last_command = None
    off_route_since = None
    slow_since = None
    min_distance = math.hypot(
        pre_state["x"] - target_x, pre_state["y"] - target_y
    )
    while steps < max_steps:
        state = _state_metadata(session, ego)
        s, px, py, cross = project_to_path(
            route_points,
            cumulative,
            state["x"],
            state["y"],
            last_s,
            window_m=PROJECTION_WINDOW_M,
        )
        spawned = _apply_obstacle_triggers(session, s, route_node_ids)
        if spawned:
            obstacles = _all_parking_obstacles()
            result.setdefault("mid_segment_obstacles", []).extend(spawned)
        tang0 = point_at_s(route_points, cumulative, s)
        tang1 = point_at_s(
            route_points, cumulative, min(cumulative[-1], s + 0.5)
        )
        if math.hypot(tang1[0] - tang0[0], tang1[1] - tang0[1]) < 1e-6:
            tang0, tang1 = route_points[-2], route_points[-1]
        tang_len = math.hypot(tang1[0] - tang0[0], tang1[1] - tang0[1])
        tang_x = (tang1[0] - tang0[0]) / tang_len
        tang_y = (tang1[1] - tang0[1]) / tang_len
        signed_lateral = -(
            (state["x"] - px) * tang_y - (state["y"] - py) * tang_x
        )
        distance = math.hypot(state["x"] - target_x, state["y"] - target_y)
        heading_error = math.degrees(
            (math.radians(state["yaw"]) - PARKING_SLOT_HEADING_RAD + math.pi)
            % (2.0 * math.pi)
            - math.pi
        )
        safety_details = {}
        blocked, min_hit, ground = nav01b.safety_check(
            session,
            ego,
            route_points,
            cumulative,
            s,
            floor_probe_z=FLOOR_PROBE_Z,
            ray_z_offset=SAFETY_RAY_Z_OFFSET,
            min_probe_distance_m=float(args.safety_probe_distance),
            stop_distance_m=PARKING_STOP_DISTANCE_M,
            details_out=safety_details,
        )
        clearance = footprint_clearance(
            state["x"],
            state["y"],
            math.radians(state["yaw"]),
            PARKING_FOOTPRINT,
            obstacles,
        )
        last_state, last_s, last_cross = state, s, cross
        last_clearance, last_min_hit, last_ground = clearance, min_hit, ground
        last_details = safety_details
        min_distance = min(min_distance, distance)
        collision_count = _collision_count()
        if collision_count > baseline_collisions:
            reason = "collision"
            break
        if blocked:
            reason = "obstacle"
            break
        if (
            clearance["min_clearance_m"] is not None
            and clearance["min_clearance_m"] < PARKING_STATIC_CLEARANCE_M
        ):
            reason = "clearance_margin"
            break
        if state["t"] - start_t > max_sim_seconds:
            reason = "timeout"
            break
        if abs(cross) > 0.60:
            off_route_since = off_route_since or state["t"]
            if state["t"] - off_route_since > 0.8:
                reason = "off_route"
                break
        else:
            off_route_since = None
        if (
            distance <= PARKING_SUCCESS_DISTANCE_M
            and abs(heading_error) <= PARKING_SUCCESS_HEADING_DEG
            and state["speed"] <= 0.15
        ):
            reason = "success"
            break
        if (
            abs(state["x"] - target_x) <= 0.20
            and abs(state["y"] - target_y) <= 0.50
            and s >= cumulative[-1] - 0.7
            and state["speed"] <= 0.25
        ):
            reason = "alignment"
            break
        if min_distance <= 0.25 and distance > min_distance + 0.15:
            reason = "overshoot"
            break
        if state["speed"] < 0.05:
            slow_since = slow_since or state["t"]
            if state["t"] - slow_since > 10.0 and distance > 0.3:
                reason = "stuck"
                break
        else:
            slow_since = None
        approach_cap = speed_cap
        if distance < 1.0:
            approach_cap = min(
                speed_cap, max(0.10, speed_cap * max(distance, 0.05))
            )
        final_leg = s >= cumulative[-1] - 2.0
        command, info = parking_track_command(
            x=state["x"],
            y=state["y"],
            yaw_rad=math.radians(state["yaw"]),
            speed_mps=state["speed"],
            points=route_points,
            cumulative=cumulative,
            s=s,
            distance_to_slot_m=distance,
            signed_lateral_m=signed_lateral,
            speed_cap_mps=approach_cap,
            cross_gain=2.5 if final_leg else 1.5,
            heading_gain=0.3 if final_leg else 0.1,
        )
        if distance < 0.8 and state["speed"] > approach_cap + 0.08:
            command = ControlCommand(
                throttle=0.0, brake=0.4, steer=command.steer
            )
        ego.apply_control(
            carla.VehicleControl(
                throttle=command.throttle,
                steer=command.steer,
                brake=command.brake,
            )
        )
        last_command = {
            "throttle": round(command.throttle, 3),
            "brake": round(command.brake, 3),
            "steer": round(command.steer, 3),
        }
        result["records"].append(
            {
                "step": steps,
                "t": state["t"],
                "x": state["x"],
                "y": state["y"],
                "z": state["z"],
                "yaw": state["yaw"],
                "speed": state["speed"],
                "throttle": round(command.throttle, 3),
                "brake": round(command.brake, 3),
                "steer": round(command.steer, 3),
                "progress_m": round(s, 3),
                "cross_track_m": round(cross, 3),
                "signed_lateral_m": round(signed_lateral, 3),
                "distance_to_target_m": round(distance, 3),
                "heading_error_deg": round(heading_error, 3),
                "safety_min_hit_m": None if min_hit is None else round(min_hit, 3),
                "ground_z": ground,
                "static_clearance_m": clearance["min_clearance_m"],
                "collision_count": collision_count,
                **info.to_metadata(),
                "decision_direction": decision_direction,
                "selected_edge": list(arbitration.selected_edge),
            }
        )
        session.tick()
        steps += 1

    if reason is None:
        reason = "timeout"
    result["steps"] = steps
    ego.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0, steer=0.0))
    for _ in range(120):
        session.tick()
        parked_state = _state_metadata(session, ego)
        if parked_state["speed"] < 0.03:
            break
    if reason == "alignment":
        alignment = _align_parking_pose(
            session, ego, target_x, target_y, obstacles, args
        )
        result["alignment"] = alignment
        result["records"].extend(alignment["records"])
        reason = "success" if alignment["success"] else "alignment_failed"
        post_state = _state_metadata(session, ego, with_road=True)
    else:
        session.tick(5)
        post_state = _state_metadata(session, ego, with_road=True)
    result["stop_reason"] = reason
    result["post_state"] = post_state
    result["stopped"] = post_state["speed"] < 0.05
    result["moved_m"] = round(
        math.hypot(
            post_state["x"] - pre_state["x"], post_state["y"] - pre_state["y"]
        ),
        3,
    )
    result["distance_to_target_m"] = round(
        math.hypot(post_state["x"] - target_x, post_state["y"] - target_y), 3
    )
    result["final_heading_error_deg"] = round(
        math.degrees(
            (math.radians(post_state["yaw"]) - PARKING_SLOT_HEADING_RAD + math.pi)
            % (2.0 * math.pi)
            - math.pi
        ),
        3,
    )
    result["final_static_clearance"] = footprint_clearance(
        post_state["x"],
        post_state["y"],
        math.radians(post_state["yaw"]),
        PARKING_FOOTPRINT,
        obstacles,
    )
    result["segment_success"] = bool(
        reason == "success"
        and result["distance_to_target_m"] <= 0.25
        and abs(result["final_heading_error_deg"]) <= 5.0
        and result["stopped"]
    )
    result["stop_diagnostics"] = _segment_stop_diagnostics(
        step=max(0, steps - 1),
        state=last_state,
        target_node_id=target_node_id,
        target_x=target_x,
        target_y=target_y,
        s=last_s,
        cross_track_m=last_cross,
        points=route_points,
        cumulative=cumulative,
        safety_details=last_details,
        min_hit=last_min_hit,
        ground=last_ground,
        monitor={"stop_reason": reason, "parking": True},
        monitor_reason=reason,
        ego=ego,
        route_node_ids=route_node_ids,
        last_command=last_command,
    )
    return result


def _drive_segment(
    session,
    ego,
    arbitration,
    args,
    round_index: int,
    decision_direction: str,
) -> dict:
    """Follow the selected route for a bounded number of nodes, then stop.

    The model selected the *first* edge of ``selected_route_node_ids``. The
    segment may continue along that same A* route to a later decision point;
    this avoids calling the model every control cycle while still re-observing
    after real motion.
    """

    selected_nodes, selected_points = execution_route(arbitration, GRAPH)
    route_node_ids = list(selected_nodes)
    route_points = list(selected_points)
    cumulative = cumulative_lengths(route_points)
    target_index = parking_continuation_target_index(
        route_node_ids,
        args.segment_nodes,
        entry_node_ids=PARKING_ARC_ENTRY_NODE_IDS,
        goal_node_ids=PARKING_GOAL_NODES,
    )
    target_node_id = route_node_ids[target_index]
    if (
        SCENARIO == "carpark_parking"
        and target_node_id in PARKING_GOAL_NODES
    ):
        return _drive_parking_segment(
            session,
            ego,
            arbitration,
            args,
            round_index,
            decision_direction,
        )
    target_x, target_y = NODES[target_node_id]
    pre_state = _state_metadata(session, ego, with_road=True)
    start_s, _, _, pre_cross = project_to_path(
        route_points,
        cumulative,
        pre_state["x"],
        pre_state["y"],
        0.0,
        window_m=PROJECTION_WINDOW_M,
    )
    monitor = SegmentMonitor(
        goal_x=target_x,
        goal_y=target_y,
        start_t=pre_state["t"],
        start_progress_s=start_s,
        arrival_radius_m=ARRIVAL_RADIUS_M,
        max_sim_seconds=args.max_segment_sim_seconds,
    )

    precheck_heights = (
        PRECHECK_RAY_Z_OFFSETS if len(arbitration.candidates) > 1 else None
    )
    precheck_lateral = (
        PRECHECK_LATERAL_OFFSETS if len(arbitration.candidates) > 1 else None
    )
    precheck_origins = (
        PRECHECK_PATH_ORIGIN_S if len(arbitration.candidates) > 1 else None
    )
    parking_origins, parking_stop = _parking_precheck_plan(
        route_node_ids, target_node_id, start_s
    )
    if parking_origins is not None:
        precheck_origins = parking_origins
    initial_details = {}
    initial_blocked, initial_min, initial_ground = nav01b.safety_check(
        session,
        ego,
        route_points,
        cumulative,
        start_s,
        floor_probe_z=FLOOR_PROBE_Z,
        ray_z_offset=SAFETY_RAY_Z_OFFSET,
        ray_z_offsets=precheck_heights,
        lateral_offsets=precheck_lateral,
        path_origin_s=precheck_origins,
        stop_distance_m=parking_stop,
        min_probe_distance_m=float(args.safety_probe_distance),
        details_out=initial_details,
    )
    result = {
        "target_node_id": target_node_id,
        "target_index": target_index,
        "target_xy": {"x": target_x, "y": target_y},
        "model_selected_edge": list(arbitration.selected_edge),
        "route_node_ids": route_node_ids,
        "route_points": [list(point) for point in route_points],
        "pre_state": pre_state,
        "pre_cross_track_m": round(pre_cross, 3),
        "initial_safety": {
            "blocked": initial_blocked,
            "min_hit_m": None if initial_min is None else round(initial_min, 3),
            "ground_z": initial_ground,
        },
        "initial_safety_details": initial_details,
        "records": [],
        "steps": 0,
        "stop_reason": None,
        "model_control_note": (
            "the model selected this edge; every control value below was "
            "produced by the shared 01B Pure Pursuit controller"
        ),
    }
    if initial_blocked:
        result["stop_reason"] = "safety_precheck"
        result["post_state"] = pre_state
        result["stopped"] = pre_state["speed"] < 0.25
        result["distance_to_target_m"] = round(
            math.hypot(pre_state["x"] - target_x, pre_state["y"] - target_y), 3
        )
        result["segment_success"] = False
        result["stop_diagnostics"] = _segment_stop_diagnostics(
            step=0,
            state=pre_state,
            target_node_id=target_node_id,
            target_x=target_x,
            target_y=target_y,
            s=start_s,
            cross_track_m=pre_cross,
            points=route_points,
            cumulative=cumulative,
            safety_details=initial_details,
            min_hit=initial_min,
            ground=initial_ground,
            monitor={"stop_reason": "safety_precheck"},
            monitor_reason="safety_precheck",
            ego=ego,
            route_node_ids=route_node_ids,
            last_command=None,
        )
        return result

    steps = 0
    reason = None
    last_command = None
    last_state = pre_state
    last_s = start_s
    last_cross = pre_cross
    last_details = initial_details
    last_min_hit = initial_min
    last_ground = initial_ground
    while steps < args.max_steps:
        state = _state_metadata(session, ego)
        s, _, _, cross = project_to_path(
            route_points,
            cumulative,
            state["x"],
            state["y"],
            monitor.last_progress_s,
            window_m=PROJECTION_WINDOW_M,
        )
        spawned = _apply_obstacle_triggers(session, s, route_node_ids)
        if spawned:
            result.setdefault("mid_segment_obstacles", []).extend(spawned)
        distance_goal = math.hypot(state["x"] - target_x, state["y"] - target_y)
        safety_details = {}
        blocked, min_hit, ground = nav01b.safety_check(
            session,
            ego,
            route_points,
            cumulative,
            s,
            floor_probe_z=FLOOR_PROBE_Z,
            ray_z_offset=SAFETY_RAY_Z_OFFSET,
            details_out=safety_details,
        )
        last_state, last_s, last_cross = state, s, cross
        last_details, last_min_hit, last_ground = safety_details, min_hit, ground
        reason = monitor.update(
            t=state["t"],
            x=state["x"],
            y=state["y"],
            speed_mps=state["speed"],
            progress_s=s,
            cross_track_m=cross,
            blocked=blocked,
        )
        if reason is not None:
            result["stop_diagnostics"] = _segment_stop_diagnostics(
                step=steps,
                state=state,
                target_node_id=target_node_id,
                target_x=target_x,
                target_y=target_y,
                s=s,
                cross_track_m=cross,
                points=route_points,
                cumulative=cumulative,
                safety_details=safety_details,
                min_hit=min_hit,
                ground=ground,
                monitor=monitor.to_metadata(),
                monitor_reason=reason,
                ego=ego,
                route_node_ids=route_node_ids,
                last_command=last_command,
            )
            break
        command, info = pure_pursuit_command(
            x=state["x"],
            y=state["y"],
            yaw_rad=math.radians(state["yaw"]),
            speed_mps=state["speed"],
            points=route_points,
            cumulative=cumulative,
            s=s,
            distance_to_goal_m=distance_goal,
            goal_slowdown_distance_m=2.5,
            goal_speed_mps=1.2,
        )
        ego.apply_control(
            carla.VehicleControl(
                throttle=command.throttle,
                steer=command.steer,
                brake=command.brake,
            )
        )
        last_command = {
            "throttle": round(command.throttle, 3),
            "brake": round(command.brake, 3),
            "steer": round(command.steer, 3),
        }
        result["records"].append(
            {
                "step": steps,
                "t": state["t"],
                "x": state["x"],
                "y": state["y"],
                "z": state["z"],
                "yaw": state["yaw"],
                "speed": state["speed"],
                "throttle": round(command.throttle, 3),
                "brake": round(command.brake, 3),
                "steer": round(command.steer, 3),
                "progress_m": round(s, 3),
                "cross_track_m": round(cross, 3),
                "distance_to_target_m": round(distance_goal, 3),
                "safety_min_hit_m": None if min_hit is None else round(min_hit, 3),
                "ground_z": ground,
                **info.to_metadata(),
                "decision_direction": decision_direction,
                "selected_edge": list(arbitration.selected_edge),
            }
        )
        session.tick()
        steps += 1

    if reason is None:
        reason = "timeout"
        monitor.stop_reason = reason
        result["stop_diagnostics"] = _segment_stop_diagnostics(
            step=max(0, steps - 1),
            state=last_state,
            target_node_id=target_node_id,
            target_x=target_x,
            target_y=target_y,
            s=last_s,
            cross_track_m=last_cross,
            points=route_points,
            cumulative=cumulative,
            safety_details=last_details,
            min_hit=last_min_hit,
            ground=last_ground,
            monitor=monitor.to_metadata(),
            monitor_reason=reason,
            ego=ego,
            route_node_ids=route_node_ids,
            last_command=last_command,
            max_steps=True,
        )
    result["stop_reason"] = reason
    result["steps"] = steps
    session.brake_to_stop(ego, max_ticks=120)
    post_state = _state_metadata(session, ego, with_road=True)
    if post_state["speed"] >= 0.25:
        session.brake_to_stop(ego, max_ticks=120)
        post_state = _state_metadata(session, ego, with_road=True)
    result["post_state"] = post_state
    result["stopped"] = post_state["speed"] < 0.25
    result["distance_to_target_m"] = round(
        math.hypot(post_state["x"] - target_x, post_state["y"] - target_y), 3
    )
    result["moved_m"] = round(
        math.hypot(post_state["x"] - pre_state["x"], post_state["y"] - pre_state["y"]),
        3,
    )
    result["segment_success"] = bool(
        reason == "success"
        and result["distance_to_target_m"] <= ARRIVAL_RADIUS_M + 0.45
        and result["stopped"]
    )
    result["monitor"] = monitor.to_metadata()
    return result


def _brake_and_state(session, ego):
    """Best-effort stop, then a real state read. Returns (state, brake_error)."""

    brake_error = None
    try:
        session.brake_to_stop(ego, max_ticks=120)
    except Exception as exc:  # a failed brake must be reported, not hidden
        brake_error = f"{type(exc).__name__}: {exc}"
    try:
        state = _state_metadata(session, ego, with_road=True)
    except Exception:
        state = None
    return state, brake_error


def _validate_kernel_correlation(response, request, intent, transaction):
    """Check that the Host result, bridge result and requested intent agree.

    Returns ``(error, output_object)``. ``error`` is ``None`` only when the
    Kernel completed the capability, the bridge authorized and finished the
    execution, and both sides report the same real post-execution state.
    """

    if response.request_id != request.request_id:
        return (
            "response request_id does not match the request: "
            f"{response.request_id!r} != {request.request_id!r}",
            None,
        )
    if response.host_kind != HostKind.KERNEL:
        return f"response host_kind is {response.host_kind!r}, not 'kernel'", None
    if not response.ok:
        detail = ""
        if response.error:
            detail = f" ({response.error.get('code')}: {response.error.get('message')})"
        return f"Kernel response is not ok{detail}", None
    if response.execution_status != "completed":
        return (
            f"Kernel execution_status is {response.execution_status!r}, not 'completed'",
            None,
        )
    if response.output is None:
        return "Kernel completed without a parking.move output", None
    try:
        output = json.loads(response.output)
    except ValueError as exc:
        return f"Kernel output is not valid JSON: {exc}", None
    if not isinstance(output, dict):
        return "Kernel output is not a JSON object", None
    if output.get("output_version") != "2":
        return f"unexpected output_version {output.get('output_version')!r}", None
    if output.get("status") != "carla_completed":
        return f"unexpected output status {output.get('status')!r}", None
    if output.get("execution_mode") != "carla":
        return f"unexpected execution_mode {output.get('execution_mode')!r}", None
    if output.get("action") != intent.action:
        return "output action does not match the intent", None
    if output.get("intent_id") != intent.intent_id:
        return "output intent_id does not match the intent", None
    if output.get("request_id") != request.request_id:
        return "output request_id does not match the IPC request", None
    if output.get("target") != intent.target.to_object():
        return "output target does not match the intent target", None

    if transaction is None:
        return "the capability bridge has no transaction for this request", None
    if transaction.get("request_id") != request.request_id:
        return "bridge transaction request_id does not match", None
    if transaction.get("intent_id") != intent.intent_id:
        return "bridge transaction intent_id does not match", None
    if transaction.get("authorized") is not True:
        return f"bridge did not authorize the request: {transaction.get('reason')}", None
    if transaction.get("handler_started") is not True:
        return "bridge never started the CARLA execution handler", None
    if transaction.get("handler_finished") is not True:
        return "bridge CARLA execution handler did not finish", None
    if transaction.get("status") != "completed":
        return (
            f"bridge execution status is {transaction.get('status')!r}, "
            f"reason={transaction.get('reason')!r}",
            None,
        )

    vehicle = output.get("vehicle")
    tx_vehicle = transaction.get("vehicle")
    if not isinstance(vehicle, dict) or not isinstance(tx_vehicle, dict):
        return "Kernel or bridge result has no vehicle evidence", None
    if vehicle.get("stopped") is not True or tx_vehicle.get("stopped") is not True:
        return "vehicle was not confirmed stopped in the Kernel/bridge result", None
    for key in ("pre_state", "post_state"):
        left, right = vehicle.get(key), tx_vehicle.get(key)
        if not isinstance(left, dict) or not isinstance(right, dict):
            return f"{key} is missing from the Kernel/bridge result", None
        for field in ("x", "y", "speed"):
            try:
                same = math.isclose(
                    float(left[field]), float(right[field]), rel_tol=0.0, abs_tol=1e-9
                )
            except (KeyError, TypeError, ValueError):
                return f"{key}.{field} is not a finite number", None
            if not same:
                return (
                    f"{key}.{field} differs between Kernel and bridge: "
                    f"{left[field]!r} != {right[field]!r}",
                    None,
                )
    try:
        same_moved = math.isclose(
            float(vehicle["moved_m"]),
            float(tx_vehicle["moved_m"]),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
    except (KeyError, TypeError, ValueError):
        return "moved_m is missing or not numeric", None
    if not same_moved:
        return "moved_m differs between Kernel and bridge", None
    return None, output


def _kernel_session_control(
    host_client,
    capability_id: str,
    payload: dict,
    request_id: str,
):
    """Send one Kernel Host session control request (create/get/close).

    Returns ``(response, output_object_or_None)``. The Host owns the real
    ``ak::Session`` and ``ak::context::Context``; this helper only carries the
    control request over the existing IPC protocol.
    """

    request = Request(
        request_id=request_id,
        capability_id=capability_id,
        payload=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
    response = host_client.send(request)
    output = None
    if isinstance(response.output, str):
        try:
            parsed = json.loads(response.output)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            output = parsed
    return response, output


def _execute_segment_via_kernel(
    session,
    ego,
    arbitration,
    args,
    round_index,
    decision_direction,
    intent_id,
    host_client,
    bridge,
    host_session_id=None,
    host_context_revision=None,
) -> dict:
    """Execute one arbitrated segment through the real Kernel host.

    Preconditions: the decision chain and route arbitration have already
    selected this route. This function performs the pre-execution safety gate,
    then registers a single-use permit, builds a validated AgentIntent and
    submits it. The Kernel's registered ``parking.move`` invoker calls back into
    the existing 01B controller via the bridge. No vehicle control value is
    ever taken from the model or from ``AgentIntent.target.heading``.
    """

    selected_nodes, selected_points = execution_route(arbitration, GRAPH)
    route_node_ids = list(selected_nodes)
    route_points = list(selected_points)
    target_index = parking_continuation_target_index(
        route_node_ids,
        args.segment_nodes,
        entry_node_ids=PARKING_ARC_ENTRY_NODE_IDS,
        goal_node_ids=PARKING_GOAL_NODES,
    )
    target_node_id = route_node_ids[target_index]
    target_x, target_y = NODES[target_node_id]
    pre_state = _state_metadata(session, ego, with_road=True)
    cumulative = cumulative_lengths(route_points)
    start_s, _, _, pre_cross = project_to_path(
        route_points,
        cumulative,
        pre_state["x"],
        pre_state["y"],
        0.0,
        window_m=PROJECTION_WINDOW_M,
    )
    precheck_heights = (
        PRECHECK_RAY_Z_OFFSETS if len(arbitration.candidates) > 1 else None
    )
    precheck_lateral = (
        PRECHECK_LATERAL_OFFSETS if len(arbitration.candidates) > 1 else None
    )
    precheck_origins = (
        PRECHECK_PATH_ORIGIN_S if len(arbitration.candidates) > 1 else None
    )
    parking_origins, parking_stop = _parking_precheck_plan(
        route_node_ids, target_node_id, start_s
    )
    if parking_origins is not None:
        precheck_origins = parking_origins
    initial_details = {}
    blocked, min_hit, ground = nav01b.safety_check(
        session,
        ego,
        route_points,
        cumulative,
        start_s,
        floor_probe_z=FLOOR_PROBE_Z,
        ray_z_offset=SAFETY_RAY_Z_OFFSET,
        ray_z_offsets=precheck_heights,
        lateral_offsets=precheck_lateral,
        path_origin_s=precheck_origins,
        stop_distance_m=parking_stop,
        min_probe_distance_m=float(args.safety_probe_distance),
        details_out=initial_details,
    )
    execution = {
        "target_node_id": target_node_id,
        "target_index": target_index,
        "target_xy": {"x": target_x, "y": target_y},
        "model_selected_edge": list(arbitration.selected_edge),
        "route_node_ids": route_node_ids,
        "route_points": [list(point) for point in route_points],
        "pre_state": pre_state,
        "pre_cross_track_m": round(pre_cross, 3),
        "initial_safety": {
            "blocked": blocked,
            "min_hit_m": None if min_hit is None else round(min_hit, 3),
            "ground_z": ground,
        },
        "initial_safety_details": initial_details,
        "records": [],
        "steps": 0,
        "model_control_note": (
            "the model selected this edge; every control value was produced by "
            "the shared 01B Pure Pursuit controller inside the Kernel-invoked "
            "CARLA execution"
        ),
    }

    if blocked:
        post_state, brake_error = _brake_and_state(session, ego)
        post_state = post_state or pre_state
        execution.update(
            {
                "executed": False,
                "kernel": {
                    "called": False,
                    "reason": "safety_precheck_blocked",
                },
                "stop_reason": "safety_precheck",
                "post_state": post_state,
                "stopped": post_state["speed"] < 0.25,
                "moved_m": 0.0,
                "segment_success": False,
                "brake_error": brake_error,
                "stop_diagnostics": _segment_stop_diagnostics(
                    step=0,
                    state=pre_state,
                    target_node_id=target_node_id,
                    target_x=target_x,
                    target_y=target_y,
                    s=start_s,
                    cross_track_m=pre_cross,
                    points=route_points,
                    cumulative=cumulative,
                    safety_details=initial_details,
                    min_hit=min_hit,
                    ground=ground,
                    monitor={"stop_reason": "safety_precheck"},
                    monitor_reason="safety_precheck",
                    ego=ego,
                    route_node_ids=route_node_ids,
                    last_command=None,
                ),
            }
        )
        return execution

    if (
        SCENARIO == "carpark_parking"
        and target_node_id in PARKING_GOAL_NODES
    ):
        # The declared target heading is the final parked heading (west), not
        # the bearing from the current pose to the bay centre.
        heading = PARKING_SLOT_HEADING_RAD
    else:
        heading = math.atan2(target_y - pre_state["y"], target_x - pre_state["x"])
    intent = AgentIntent(
        intent_id=intent_id,
        target=Target(x=target_x, y=target_y, heading=heading),
    )
    payload = intent.to_payload()
    request_id = f"carla-02-r{round_index:02d}-req-{pre_state['snapshot_frame']}"
    bridge.register_permit(
        request_id=request_id,
        intent_id=intent.intent_id,
        target=intent.target.to_object(),
        payload=payload,
        context={
            "arbitration": arbitration,
            "round_index": round_index,
            "direction": decision_direction,
            "pre_state": pre_state,
        },
    )
    execution_domain = {
        "capability": "parking.move",
        "round": round_index,
        "intent_id": intent.intent_id,
        "target_node_id": target_node_id,
        "selected_edge": list(arbitration.selected_edge),
        "route_node_ids": route_node_ids,
        "direction": decision_direction,
        "parking": PARKING_CONTEXT,
    }
    request = build_request(
        intent,
        request_id=request_id,
        session_id=host_session_id,
        expected_context_revision=host_context_revision,
        domain=execution_domain,
    )
    kernel = {
        "called": True,
        "capability_id": request.capability_id,
        "request_id": request_id,
        "intent_id": intent.intent_id,
        "intent_payload": payload,
        "target": intent.target.to_object(),
        "authorization": (
            "IssueRuntimeExecutionAuthority -> Port().Submit/Observe -> "
            "Runtime::Run -> registered parking.move invoker"
        ),
        "route_target_node_id": target_node_id,
        "route_node_ids": route_node_ids,
        "session_id": host_session_id,
        "expected_context_revision": host_context_revision,
        "domain": execution_domain,
    }

    started = time.monotonic()
    try:
        response = host_client.send(request)
    except Exception as exc:
        bridge.revoke_permit(request_id)
        kernel["response"] = None
        kernel["error"] = {"type": type(exc).__name__, "message": str(exc)}
        post_state, brake_error = _brake_and_state(session, ego)
        post_state = post_state or pre_state
        execution.update(
            {
                "executed": True,
                "kernel": kernel,
                "stop_reason": "kernel_transport_failed",
                "post_state": post_state,
                "stopped": post_state["speed"] < 0.25,
                "moved_m": round(
                    math.hypot(
                        post_state["x"] - pre_state["x"],
                        post_state["y"] - pre_state["y"],
                    ),
                    3,
                ),
                "segment_success": False,
                "brake_error": brake_error,
            }
        )
        return execution
    kernel["transport_seconds"] = round(time.monotonic() - started, 3)
    transaction = bridge.get_transaction(request_id)
    kernel["response"] = {
        "request_id": response.request_id,
        "host_kind": response.host_kind,
        "accepted": response.accepted,
        "submission_status": response.submission_status,
        "observation_status": response.observation_status,
        "execution_status": response.execution_status,
        "error": None if response.error is None else dict(response.error),
        "output": response.output,
        "session_id": response.session_id,
        "session_state": response.session_state,
        "task_id": response.task_id,
        "workflow_id": response.workflow_id,
        "context_revision": response.context_revision,
        "turn": response.turn,
        "context_updated": response.context_updated,
    }
    kernel["context_before"] = (
        None
        if response.context_before is None
        else dict(response.context_before)
    )
    kernel["context_after"] = (
        None if response.context_after is None else dict(response.context_after)
    )
    kernel["bridge_transaction"] = transaction

    validation_error, output = _validate_kernel_correlation(
        response, request, intent, transaction
    )
    if validation_error is not None:
        post_state = None
        tx_vehicle = (
            transaction.get("vehicle")
            if isinstance(transaction, dict)
            and isinstance(transaction.get("vehicle"), dict)
            else None
        )
        if tx_vehicle is not None:
            candidate = tx_vehicle.get("post_state")
            if isinstance(candidate, dict):
                post_state = dict(candidate)
        brake_error = None
        if post_state is None or post_state.get("speed", 1.0) >= 0.25:
            post_state, brake_error = _brake_and_state(session, ego)
        post_state = post_state or pre_state
        kernel["validation_error"] = validation_error
        execution.update(
            {
                "executed": bool(
                    transaction and transaction.get("handler_started") is True
                ),
                "kernel": kernel,
                "stop_reason": "kernel_validation_failed",
                "post_state": post_state,
                "stopped": post_state["speed"] < 0.25,
                "moved_m": round(
                    math.hypot(
                        post_state["x"] - pre_state["x"],
                        post_state["y"] - pre_state["y"],
                    ),
                    3,
                ),
                "segment_success": False,
                "brake_error": brake_error,
                "stop_diagnostics": (
                    None if tx_vehicle is None else tx_vehicle.get("stop_diagnostics")
                ),
                "stop_detail": (
                    None if tx_vehicle is None else tx_vehicle.get("stop_detail")
                ),
            }
        )
        return execution

    vehicle = dict(transaction["vehicle"])
    execution.update(vehicle)
    execution.update(
        {
            "authorization": kernel["authorization"],
            "model_selected_edge": list(arbitration.selected_edge),
            "route_node_ids": route_node_ids,
            "route_points": [list(point) for point in route_points],
            "pre_cross_track_m": round(pre_cross, 3),
            "initial_safety": {
                "blocked": blocked,
                "min_hit_m": None if min_hit is None else round(min_hit, 3),
                "ground_z": ground,
            },
            "model_control_note": (
                "the model selected this edge; every control value was produced "
                "by the shared 01B Pure Pursuit controller inside the "
                "Kernel-invoked CARLA execution"
            ),
            "moved_m": output["vehicle"]["moved_m"],
            "executed": True,
            "kernel": kernel,
            "segment_success": bool(vehicle.get("segment_success"))
            and vehicle.get("stopped") is True,
        }
    )
    return execution


def _redecision_history_note(
    *,
    previous_decision,
    previous_execution,
    previous_post_state,
    current_state,
    image_sha,
) -> str:
    """Build factual context for the one extra intersection decision."""

    parts = []
    if previous_decision:
        parts.append(
            "上一轮最终决策："
            f"Relative position={previous_decision.get('position')}，"
            f"Next direction={previous_decision.get('direction')}，"
            f"Evidence={previous_decision.get('evidence')}"
            + (
                "（该决策来自一次路口重决策）"
                if previous_decision.get("redecision")
                else ""
            )
            + "。"
        )
    if previous_execution:
        moved = previous_execution.get("moved_m")
        parts.append(
            "上一轮执行："
            f"路段目标={previous_execution.get('target_node_id')}，"
            f"实际位移={None if moved is None else round(float(moved), 3)} m，"
            f"stop_reason={previous_execution.get('stop_reason')}，"
            f"Kernel执行状态={previous_execution.get('kernel_execution_status')}。"
        )
    if previous_post_state:
        parts.append(
            "上一轮后置真实状态："
            f"x={previous_post_state['x']:.3f}，"
            f"y={previous_post_state['y']:.3f}，"
            f"yaw={previous_post_state['yaw']:.3f}°，"
            f"speed={previous_post_state['speed']:.3f} m/s。"
        )
    else:
        parts.append("这是第一轮导航，没有上一轮执行结果。")
    parts.append(
        "本轮观察："
        f"frame_id={current_state.get('snapshot_frame')}，"
        f"x={current_state['x']:.3f}，y={current_state['y']:.3f}，"
        f"yaw={current_state['yaw']:.3f}°，"
        f"speed={current_state['speed']:.3f} m/s，"
        f"图像SHA256={image_sha}。"
    )
    return " ".join(parts)


def run(args, runtime: dict | None = None) -> tuple[int, dict]:
    runtime = dict(runtime or {})
    keep_runtime = bool(runtime.get("keep_runtime"))
    provided_session = runtime.get("session")
    provided_ego = runtime.get("ego")
    provided_host = runtime.get("host_client")
    provided_bridge = runtime.get("bridge")
    out_dir = Path(args.output_dir) if args.output_dir else REPO_ROOT / "docs" / "evidence" / "carla-01e"
    out_dir.mkdir(parents=True, exist_ok=True)
    task_label = getattr(args, "task_label", TASK_LABEL)
    run_prefix = getattr(args, "run_prefix", None) or "carla-06"
    run_id = f"{run_prefix}-{SCENARIO}-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    targets = [item.strip() for item in args.targets.split(",") if item.strip()]
    if not targets:
        raise ValueError("--targets must name at least one visible target")
    round_fovs = [float(item) for item in args.round_fovs.split(",") if item.strip()]
    if not round_fovs or any(fov <= 0 or fov >= 180 for fov in round_fovs):
        raise ValueError("--round-fovs must contain one or more FOVs in (0, 180)")
    route = resolve_route(
        GRAPH,
        args.start_node,
        args.goal_node,
        start_previous_node_id=args.start_previous_node,
        start_yaw_deg=args.start_yaw_deg,
    )
    start_yaw_deg = math.degrees(route.start_yaw_rad)
    # A route to the current parking target must not be planned through a
    # different declared parking target (the undirected graph would otherwise
    # offer a long loop through the other bay's slot).
    # Only exclude parking goals that exist in this scenario's graph. The
    # parking-slot node belongs to the carpark graph and must not be passed as
    # an excluded node to a Town10 route arbitration.
    other_parking_goals = {
        node
        for node in (PARKING_GOAL_NODES - {route.goal_node_id})
        if GRAPH.has_node(node)
    }
    route_name = args.route_name or (
        f"{route.start_node_id}-to-{route.goal_node_id}"
    )
    if args.spawn_x is None:
        spawn_x, spawn_y = NODES[route.start_node_id]
        spawn_pose_source = "start_node"
    else:
        spawn_x, spawn_y = float(args.spawn_x), float(args.spawn_y)
        if math.hypot(
            spawn_x - NODES[route.start_node_id][0],
            spawn_y - NODES[route.start_node_id][1],
        ) > MAX_NODE_DISTANCE_M:
            raise ValueError(
                "explicit spawn pose is more than "
                f"{MAX_NODE_DISTANCE_M:.1f} m from the start node"
            )
        spawn_pose_source = "explicit_near_start_node"
    host_session_id = runtime.get("host_session_id")
    host_context_revision = runtime.get("host_context_revision")
    kernel_exe = None
    requested_kernel = getattr(args, "kernel_host", None)
    if requested_kernel:
        kernel_exe = (
            os.environ.get("VLN_KERNEL_HOST_EXE")
            if requested_kernel == "env"
            else requested_kernel
        )
        if not kernel_exe:
            raise ValueError(
                "--kernel-host env requires VLN_KERNEL_HOST_EXE to be set"
            )
        if not (os.path.isfile(kernel_exe) and os.access(kernel_exe, os.X_OK)):
            raise ValueError(f"--kernel-host is not an executable file: {kernel_exe}")
        kernel_exe = os.path.abspath(kernel_exe)
    host_planner = bool(getattr(args, "host_planner", False))
    if host_planner:
        if not kernel_exe:
            raise ValueError("--host-planner requires --kernel-host")
        if not os.environ.get("VLN_TAICHU_PLANNER_BRIDGE"):
            raise ValueError(
                "--host-planner requires VLN_TAICHU_PLANNER_BRIDGE=host:port "
                "(and VLN_TAICHU_PLANNER_TOKEN) in the environment; the "
                "compiled Host owns the Kernel planner bridge configuration"
            )
    approach_only = bool(getattr(args, "target_approach_only", False))
    binding_artifact = getattr(args, "target_binding_artifact", None)
    if approach_only and binding_artifact is None:
        raise ValueError("--target-approach-only requires a bound target artifact")
    task_started_utc = utc_now()
    task_started_monotonic = time.monotonic()
    result = {
        "meta": {
            "task": task_label,
            "base_runner": "M1-VLN-CARLA-01E",
            "scenario": SCENARIO,
            "run_id": run_id,
            "route_name": route_name,
            "task_started_utc": task_started_utc,
            "map": MAP_NAME,
            "floor_z": FLOOR_Z,
            "floor_probe_z": FLOOR_PROBE_Z,
            "safety_ray_z_offset": SAFETY_RAY_Z_OFFSET,
            "safety_probe_distance_m": float(args.safety_probe_distance),
            "invert_turn_direction": INVERT_TURN_DIRECTION,
            "carla_endpoint": f"{args.host}:{args.port}",
            "model_endpoint": "http://127.0.0.1:8100/v1/chat/completions",
            "model_request": {
                "max_new_tokens": args.max_new_tokens,
                "temperature": 0.0,
                "enable_thinking": bool(args.enable_thinking),
                "stop": None if args.enable_thinking else ["</think>"],
                "timeout_s": args.timeout,
                "stream": False,
            },
            "start_node": route.start_node_id,
            "start_previous_node": route.start_previous_node_id,
            "start_yaw_deg": round(start_yaw_deg, 3),
            "start_yaw_source": route.start_yaw_source,
            "goal_node": route.goal_node_id,
            "task_id": getattr(args, "task_id", None),
            "target_id": getattr(args, "target_id", None),
            "target_binding": getattr(args, "target_binding_meta", None),
            "target_approach": getattr(args, "target_approach_meta", None),
            "route_selection": route.to_metadata(),
            "spawn_pose_requested": {
                "x": spawn_x,
                "y": spawn_y,
                "z": float(args.spawn_z),
            },
            "spawn_pose_source": spawn_pose_source,
            "targets": targets,
            "target_kind": args.target_kind,
            "target_note_template": args.target_note,
            "round_fovs": round_fovs,
            "camera_offset": list(CAM_OFFSET),
            "camera_pitch": CAM_PITCH,
            "instruction": args.instruction,
            "planned_max_rounds": args.rounds,
            "max_total_wall_seconds": args.max_total_wall_seconds,
            "segment_nodes_per_round": args.segment_nodes,
            "straight_tolerance_deg": STRAIGHT_TOLERANCE_DEG,
            "turn_limit_deg": TURN_LIMIT_DEG,
            "edge_ambiguity_tolerance_deg": EDGE_AMBIGUITY_DEG,
            "arrival_radius_m": ARRIVAL_RADIUS_M,
            "goal_distance_tolerance_m": args.goal_distance_tolerance,
            "goal_heading_tolerance_deg": args.goal_heading_tolerance_deg,
            "goal_stop_speed_mps": args.goal_stop_speed,
            "fixed_delta_seconds": FIXED_DT,
            "execution_mode": "kernel" if kernel_exe else "direct",
            "route_recovery": {
                "enabled": bool(args.recover_after_safety_stop),
                "triggers": [
                    "pre_execution_refusal",
                    "post_motion_blocked_stop",
                ],
                "max_attempts": args.max_recovery_attempts,
                "requires_new_observation": True,
                "post_stop_node": "nearest graph node to the real stopped pose",
            },
            "mid_segment_obstacle": (
                {
                    "enabled": True,
                    "round": int(args.mid_obstacle_round),
                    "edge": list(args.mid_obstacle_edge),
                    "edge_s_m": float(args.mid_obstacle_edge_s),
                    "trigger_edge_s_m": float(
                        args.mid_obstacle_trigger_edge_s
                    ),
                    "blueprint": args.mid_obstacle_blueprint,
                    "injection": (
                        "real static actor spawned from inside the "
                        "Kernel-invoked driving segment once the vehicle "
                        "passed the trigger distance"
                    ),
                }
                if getattr(args, "mid_obstacle_round", 0)
                else None
            ),
            "intersection_redecision": {
                "enabled": not args.no_route_redecision,
                "trigger": "no_compatible_route",
                "max_attempts_per_round": 1,
                "same_frame_required_when_stationary": True,
                "route_facts_source": "the failed arbitration's real candidates",
                "max_new_tokens": max(4096, args.max_new_tokens),
            },
            "agent_kernel": {
                "used": bool(kernel_exe),
                "host_exe": kernel_exe,
                "execution_timeout_ms": getattr(
                    args, "kernel_exec_timeout_ms", None
                ),
                "authorization_path": (
                    "IssueRuntimeExecutionAuthority -> Port().Submit/Observe "
                    "-> Runtime::Run -> registered parking.move invoker"
                ),
                "capability_id": "parking.move",
                "capability_provider": (
                    "vln.parking.carla" if kernel_exe else None
                ),
                "bridge": None,
                "reason": (
                    "each arbitrated segment is submitted as a validated "
                    "AgentIntent v1 request; the registered parking.move "
                    "invoker calls back into the existing 01B restricted CARLA "
                    "controller and returns the real post-execution state"
                    if kernel_exe
                    else (
                        "no --kernel-host was supplied; the runner executed "
                        "the shared CARLA controller directly"
                    )
                ),
            },
        },
        "video": (
            {
                "dir": str(args.video_dir),
                "mode": (
                    "one onboard camera per execution segment; the camera is "
                    "created after Taichu/arbitration and destroyed before the "
                    "next model call"
                ),
            }
            if getattr(args, "video_dir", None)
            else None
        ),
        "model_health": observe01c.health(),
        "graph": GRAPH.to_metadata(),
        "rounds": [],
        "task_status": TaskStatus.RUNNING,
        "status": None,
        "stop": None,
        "error": None,
    }

    task_memory = NavigationTaskMemory(
        task_id=f"{task_label}-{run_id}",
        max_entries=8,
        max_facts=32,
        max_unresolved=8,
        max_context_chars=4000,
    )
    if binding_artifact is not None:
        task_memory.record_target_binding(binding_artifact)
    target_identity = {
        "task_id": getattr(args, "task_id", None),
        "target_id": getattr(args, "target_id", None),
        "bay_id": getattr(binding_artifact, "bay_id", None),
        "slot_node_id": getattr(binding_artifact, "slot_node_id", None),
        "approach_node_id": (
            getattr(args, "target_approach_meta", None) or {}
        ).get("approach_node_id"),
        "binding_status": getattr(binding_artifact, "status", None),
    }
    result["meta"]["stm"] = {
        "implementation": "vln.stm.NavigationTaskMemory",
        "task_id": task_memory.task_id,
        "scope": "one run = one task; in-memory only",
        "update": (
            "every round records task_target, model decision, verified direction, "
            "real execution summary and post-state"
        ),
        "read": (
            "rounds >= 2 render the bounded history JSON into the next Taichu "
            "prompt as a clearly labelled non-visual history section"
        ),
    }
    result["stm"] = {
        "task_id": task_memory.task_id,
        "task_targets": targets,
        "records": [],
    }

    client = carla.Client(args.host, args.port)
    client.set_timeout(120.0)
    session = None
    ego = None
    active_round_video = None
    restore_opener = None
    host_client = None
    bridge = None
    exit_code = EXIT_UNEXPECTED
    try:
        if provided_session is not None:
            session = provided_session
            world = session.world
        else:
            world = client.get_world()
            if not world.get_map().name.endswith(MAP_NAME):
                client.load_world(MAP_NAME)
            session = nav01b.Session(
                args.host, args.port, str(out_dir), map_name=MAP_NAME
            )
        result["meta"]["server_version"] = session.client.get_server_version()
        result["meta"]["map_loaded"] = session.world.get_map().name
        if not result["meta"]["map_loaded"].endswith(MAP_NAME):
            raise RuntimeError(
                f"loaded map is {result['meta']['map_loaded']!r}, expected {MAP_NAME!r}"
            )

        path = list(route.path)
        result["planning"] = {
            "path": path,
            "status": "reachable",
            "path_length_m": round(route.length_m, 3),
            "edge_keys": [list(edge) for edge in route.edge_keys],
            "graph_note": route.graph_note,
        }
        goal_spec = GoalSpec(
            node_id=route.goal_node_id,
            x=NODES[route.goal_node_id][0],
            y=NODES[route.goal_node_id][1],
            heading_rad=route.goal_heading_rad,
            distance_tolerance_m=args.goal_distance_tolerance,
            heading_tolerance_rad=math.radians(args.goal_heading_tolerance_deg),
            stop_speed_mps=args.goal_stop_speed,
        )
        result["goal_spec"] = goal_spec.to_metadata()
        # Validate before spawning: a downward ray at a node would otherwise
        # hit the ego's own roof. Same rule as 01B.
        if provided_ego is not None:
            # The shared ego is already parked on the start node, so a
            # downward floor ray hits its roof instead of the garage floor.
            # The route nodes were validated in the accepted standalone runs;
            # per-tick floor and safety guards still run during execution.
            result["waypoint_validation"] = {
                "skipped": "existing_ego_occupies_floor_probes",
                "path": path,
            }
            valid = True
        else:
            valid, waypoint_report = nav01b.validate_waypoints(
                session,
                path,
                nodes=NODES,
                expected_floor=FLOOR_Z,
                floor_probe_z=FLOOR_PROBE_Z,
            )
            result["waypoint_validation"] = waypoint_report
        if not valid:
            raise RuntimeError("waypoint floor validation failed; refusing to drive")

        if provided_ego is not None:
            ego = provided_ego
            session.tick(5)
        else:
            session.destroy_leftovers()
            ego = session.spawn_vehicle(
                EGO_ROLE,
                spawn_x,
                spawn_y,
                float(args.spawn_z),
                start_yaw_deg,
            )
            session.tick(40)
        spawn_state = _state_metadata(session, ego, with_road=True)
        result["meta"]["spawn_pose"] = spawn_state
        with _RUN_COLLISION_LOCK:
            _RUN_COLLISION_EVENTS.clear()
        _RUN_EXTRA_OBSTACLES.clear()
        _RUN_OBSTACLE_RECORDS.clear()
        _RUN_OBSTACLE_TRIGGERS.clear()
        result["obstacles"] = []
        if SCENARIO == "carpark_parking":
            collision_bp = world.get_blueprint_library().find(
                "sensor.other.collision"
            )
            collision_bp.set_attribute("role_name", COLLISION_ROLE)
            collision_sensor = world.spawn_actor(
                collision_bp, carla.Transform(), attach_to=ego
            )
            session.actors.append(collision_sensor)

            def _on_collision(event):
                try:
                    other = event.other_actor
                    record = {
                        "frame": int(session.world.get_snapshot().frame),
                        "other_actor_id": int(other.id),
                        "other_actor_type": other.type_id,
                        "normal_impulse": {
                            "x": round(float(event.normal_impulse.x), 4),
                            "y": round(float(event.normal_impulse.y), 4),
                            "z": round(float(event.normal_impulse.z), 4),
                        },
                    }
                except Exception as exc:
                    record = {"error": f"{type(exc).__name__}: {exc}"}
                with _RUN_COLLISION_LOCK:
                    _RUN_COLLISION_EVENTS.append(record)

            collision_sensor.listen(_on_collision)
            result["meta"]["collision_sensor"] = {
                "role_name": COLLISION_ROLE,
                "attached": True,
            }
        initial_goal = evaluate_goal(
            goal_spec,
            VehiclePose(
                x=spawn_state["x"],
                y=spawn_state["y"],
                heading=math.radians(spawn_state["yaw"]),
            ),
            speed_mps=spawn_state["speed"],
            stopped=spawn_state["speed"] < args.goal_stop_speed,
        )
        result["initial_goal_evaluation"] = initial_goal.to_metadata()

        if kernel_exe:
            def _handle_kernel_execution(permit):
                """Run one already-authorized segment on the existing controller."""

                context = permit.context
                try:
                    segment = _drive_segment(
                        session,
                        ego,
                        context["arbitration"],
                        args,
                        context["round_index"],
                        context["direction"],
                    )
                    segment = dict(segment)
                    # "completed" means the capability invocation finished and
                    # returned a valid, confirmed-stopped CARLA result. Whether
                    # the segment reached its target is the separate
                    # segment_success field; a real safety stop must not be
                    # rewritten as a Kernel transport/validation failure.
                    segment["status"] = "completed"
                    return segment
                except Exception as exc:  # controller failure: brake, then report
                    post_state, brake_error = _brake_and_state(session, ego)
                    pre_state = context.get("pre_state") or post_state
                    if pre_state is None or post_state is None:
                        raise
                    node_ids = list(
                        context["arbitration"].selected_route_node_ids
                    )
                    target_index = parking_continuation_target_index(
                        node_ids,
                        args.segment_nodes,
                        entry_node_ids=PARKING_ARC_ENTRY_NODE_IDS,
                        goal_node_ids=PARKING_GOAL_NODES,
                    )
                    return {
                        "status": "failed",
                        "stop_reason": "controller_exception",
                        "pre_state": pre_state,
                        "post_state": post_state,
                        "stopped": post_state.get("speed", 1.0) < 0.25,
                        "moved_m": round(
                            math.hypot(
                                post_state["x"] - pre_state["x"],
                                post_state["y"] - pre_state["y"],
                            ),
                            3,
                        ),
                        "target_node_id": node_ids[target_index],
                        "route_node_ids": node_ids,
                        "steps": 0,
                        "records": [],
                        "segment_success": False,
                        "error": {"type": type(exc).__name__, "message": str(exc)},
                        "brake_error": brake_error,
                    }

            if provided_bridge is not None:
                bridge = provided_bridge
                bridge.set_handler(_handle_kernel_execution)
            else:
                bridge = CarlaExecutionBridge(
                    _handle_kernel_execution,
                    request_timeout_s=max(
                        30.0, args.max_segment_sim_seconds + 30.0
                    ),
                )
                bridge.start()
            if provided_host is not None:
                host_client = provided_host
            else:
                host_env = os.environ.copy()
                host_env["VLN_CARLA_EXEC_BRIDGE"] = bridge.endpoint
                host_env["VLN_CARLA_EXEC_TOKEN"] = bridge.token
                host_env[
                    "VLN_CARLA_EXEC_TIMEOUT_MS"
                ] = str(args.kernel_exec_timeout_ms)
                host_client = HostClient([kernel_exe], env=host_env)
            result["meta"]["agent_kernel"]["bridge"] = {
                "endpoint": bridge.endpoint,
                "single_use_permits": True,
                "token_recorded": False,
            }
            if host_planner or getattr(args, "session_id", None):
                host_session_id = getattr(args, "session_id", None) or run_id
                session_response, session_output = _kernel_session_control(
                    host_client,
                    "session.create",
                    {"session_id": host_session_id},
                    f"{run_id}-session-create",
                )
                created_by_this_run = True
                if (
                    session_response.error is not None
                    and session_response.error.get("code") == "session-exists"
                ):
                    created_by_this_run = False
                    session_response, session_output = _kernel_session_control(
                        host_client,
                        "session.get",
                        {"session_id": host_session_id},
                        f"{run_id}-session-get",
                    )
                if (
                    session_response.error is not None
                    or not session_response.accepted
                ):
                    error = session_response.error or {}
                    raise ValueError(
                        "Kernel persistent session setup failed: "
                        f"{error.get('code')}: {error.get('message')}"
                    )
                host_context_revision = (
                    session_response.context_revision
                    if isinstance(session_response.context_revision, int)
                    else 0
                )
                result["meta"]["host_session"] = {
                    "session_id": host_session_id,
                    "created_by_this_run": created_by_this_run,
                    "control_request_id": session_response.request_id,
                    "session_state": session_response.session_state,
                    "context_revision": host_context_revision,
                    "turn": session_response.turn,
                    "context": (
                        None if session_output is None
                        else session_output.get("context")
                    ),
                }
                result["meta"]["host_planner"] = {
                    "enabled": host_planner,
                    "capability_id": "planner.plan",
                    "planner_bridge_endpoint": (
                        os.environ.get("VLN_TAICHU_PLANNER_BRIDGE")
                        if host_planner
                        else None
                    ),
                    "planner_token_recorded": False,
                }

        expected_node_id = None
        previous_post_state = None
        previous_frame_sha = None
        previous_decision_summary = None
        previous_execution_summary = None
        goal_reached = False
        decision_rejected = False
        safety_stopped = False
        timed_out = False
        max_rounds = False
        execution_error = False
        recovery_attempts = 0
        pending_recovery = None
        previous_execution_finished_monotonic = None
        last_verified_identity = None
        visual_recovery_machine = VisualRecoveryMachine(
            budget=RecoveryBudget(
                max_total=args.max_visual_recovery_attempts,
                max_per_type=args.max_visual_recovery_per_type,
            )
        )
        for round_index in range(1, args.rounds + 1):
            if time.monotonic() - task_started_monotonic > args.max_total_wall_seconds:
                timed_out = True
                result["stop"] = {
                    "stage": "task",
                    "round": round_index,
                    "reason": "max_total_wall_seconds",
                    "detail": f"limit={args.max_total_wall_seconds} s",
                }
                break
            if (
                getattr(args, "remove_obstacles_round", 0)
                and round_index == int(args.remove_obstacles_round)
            ):
                removed_now = _remove_injected_obstacles(session, round_index)
                if removed_now:
                    result.setdefault("obstacle_removals", []).extend(
                        removed_now
                    )
            round_started_utc = utc_now()
            round_started_monotonic = time.monotonic()
            round_dir_name = f"round_{round_index:02d}"
            frame_name = f"{round_dir_name}_frame_%06d.png"
            if (
                getattr(args, "extra_obstacle_round", 0)
                and round_index == int(args.extra_obstacle_round)
                and not result.get("extra_obstacle")
            ):
                # A real obstruction that appears before this round's model
                # observation, used to prove the no-safe-route refusal. It is
                # visible in the captured frame and in the blocked-edge audit.
                extra = _spawn_demo_obstacle(
                    session,
                    world,
                    args.extra_obstacle_blueprint,
                    args.extra_obstacle_x,
                    args.extra_obstacle_y,
                    args.extra_obstacle_z,
                    args.extra_obstacle_yaw,
                    "tertiary_round_start",
                    phase="round_start",
                )
                result["extra_obstacle"] = extra
                result.setdefault("obstacles", []).append(extra)
            round_fov = round_fovs[min(round_index - 1, len(round_fovs) - 1)]
            observation_started_utc = utc_now()
            observation_started_monotonic = time.monotonic()
            (
                frame,
                state,
                image_path,
                image_sha,
                image_size,
                camera_meta,
            ) = _capture_round_observation(
                session,
                ego,
                out_dir,
                frame_name,
                fov=round_fov,
                camera_role=f"{CAM_ROLE}_r{round_index}",
            )
            observation_finished_utc = utc_now()
            round_result = {
                "round": round_index,
                "timing": {
                    "started_utc": round_started_utc,
                    "observation_started_utc": observation_started_utc,
                    "observation_finished_utc": observation_finished_utc,
                    "observation_s": round(
                        time.monotonic() - observation_started_monotonic, 3
                    ),
                },
                "observation": {
                    "camera": camera_meta,
                    "captured_utc": utc_now(),
                    "image_path": image_path,
                    "image_sha256": image_sha,
                    "image_size_bytes": image_size,
                    "frame": frame.to_metadata(),
                    "state": state,
                },
                "request": None,
                "decision": None,
                "arbitration": None,
                "execution": None,
                "linkage": build_round_linkage(
                    round_index=round_index,
                    previous_post_state=previous_post_state,
                    previous_frame_sha256=previous_frame_sha,
                    current_state=state,
                    current_frame_sha256=image_sha,
                    expected_node_id=expected_node_id,
                ),
                "target_identity": dict(target_identity),
                "status": None,
            }
            result["rounds"].append(round_result)
            if pending_recovery is not None:
                round_result["recovery"] = dict(pending_recovery)
                pending_recovery = None
            stm_context_before = task_memory.render_compact_context(max_chars=2400)
            stm_context_before_full = task_memory.render_context()
            stm_context_before_sha = observe01c.sha256_bytes(
                stm_context_before.encode("utf-8")
            )
            round_result["stm"] = {
                "task_id": task_memory.task_id,
                "round_index": round_index,
                "records_before": len(task_memory.records),
                "context_before": stm_context_before,
                "context_before_sha256": stm_context_before_sha,
                "context_before_full": stm_context_before_full,
                "context_before_full_sha256": observe01c.sha256_bytes(
                    stm_context_before_full.encode("utf-8")
                ),
                "history_used": round_index > 1,
            }

            pose = VehiclePose(x=state["x"], y=state["y"], heading=math.radians(state["yaw"]))
            intent_id = f"carla-01e-r{round_index}-f{frame.frame_id}"
            target = targets[min(round_index - 1, len(targets) - 1)]
            target_note = args.target_note.format(target=target)
            recovery_context = round_result.get("recovery")
            if recovery_context:
                if recovery_context.get("trigger") == "post_motion_blocked_stop":
                    recovery_note = (
                        "上一段在行驶中因前方真实静态障碍而安全停止。"
                        "本轮必须基于当前帧选择可安全绕行的方向；"
                        "不要重复被障碍阻挡的路线。"
                    )
                else:
                    recovery_note = (
                        "上一段因前方路线被静态障碍阻挡而安全停止。"
                        "本轮必须基于当前帧选择可安全绕行的方向；"
                        "不要重复被安全预检拒绝的直行路线。"
                    )
                target_note = target_note + "\n" + recovery_note
                round_result["observation"]["recovery_note"] = recovery_note
            history_context = stm_context_before if round_index > 1 else ""
            round_route_facts, round_route_context = _route_facts_for_prompt(
                pose=pose,
                target=target,
                expected_node_id=expected_node_id,
                goal_node_id=route.goal_node_id,
                args=args,
                excluded_nodes=other_parking_goals,
            )
            prompt = _prompt_for(
                state,
                target,
                args.target_kind,
                intent_id,
                args.instruction,
                target_note,
                history_context=history_context,
                route_context=round_route_context,
            )
            round_result["observation"]["route_facts"] = round_route_facts
            round_result["observation"]["route_context_in_prompt"] = bool(
                round_route_context
            )
            if round_route_context:
                round_result["observation"]["route_context_sha256"] = (
                    observe01c.sha256_bytes(round_route_context.encode("utf-8"))
                )
            observation = CarlaVisualObservation(
                frame=frame,
                image_path=image_path,
                image_sha256=image_sha,
                image_size_bytes=image_size,
                pose=pose,
                instruction=args.instruction,
                prompt=prompt,
            )
            round_result["observation"]["pose"] = {
                "x": pose.x,
                "y": pose.y,
                "heading": pose.heading,
            }
            round_result["observation"]["prompt_sha256"] = observe01c.sha256_bytes(
                prompt.encode("utf-8")
            )
            round_result["observation"]["intent_id"] = intent_id
            round_result["observation"]["target"] = target
            round_result["observation"]["target_note"] = target_note
            round_result["observation"]["history_context_used"] = bool(
                history_context
            )
            round_result["observation"]["history_context_sha256"] = (
                stm_context_before_sha if history_context else None
            )
            round_result["observation"]["prompt"] = prompt
            round_result["observation"]["history_context_in_prompt"] = (
                history_context in prompt if history_context else False
            )

            calls, restore_opener = observe01c.install_request_recorder()
            planner_client = None
            try:
                if host_planner:
                    planner_client = HostPlannerModelClient(
                        host_client,
                        session_id=host_session_id,
                        context_revision=host_context_revision,
                        request_id_prefix=(
                            f"cap08b-plan-r{round_index}-{intent_id}"
                        ),
                        domain={
                            "capability": "planner.plan",
                            "parking": PARKING_CONTEXT,
                            "round": round_index,
                            "intent_id": intent_id,
                            "target": target,
                            "target_kind": args.target_kind,
                            "pose": {
                                "x": state["x"],
                                "y": state["y"],
                                "yaw": state["yaw"],
                            },
                            "frame_id": frame.frame_id,
                            "image_sha256": image_sha,
                            "route_goal_node_id": route.goal_node_id,
                            "previous_round": round_index - 1,
                        },
                    )
                    model = planner_client
                else:
                    backend = ZDTaichuServerBackend(
                        max_new_tokens=args.max_new_tokens,
                        timeout=args.timeout,
                        temperature=0.0,
                        enable_thinking=args.enable_thinking,
                        stop=None if args.enable_thinking else ["</think>"],
                    )
                    model = ServerImageModelClient(backend=backend)
                inference_started = utc_now()
                inference_started_monotonic = time.monotonic()
                outcome = generate_and_decide(
                    model,
                    observation,
                    expected_identity=target,
                    intent_id=intent_id,
                )
                inference_finished = utc_now()
                inference_wall_s = time.monotonic() - inference_started_monotonic
            finally:
                if restore_opener is not None:
                    restore_opener()
                    restore_opener = None
            request = _model_request_evidence(
                calls,
                image_sha,
                inference_started=inference_started,
                inference_finished=inference_finished,
                planner_client=planner_client,
            )
            if planner_client is not None and isinstance(
                planner_client.context_revision_after, int
            ):
                # The retry must start from the revision the failed planning
                # exchange actually wrote, not from the pre-call revision.
                host_context_revision = planner_client.context_revision_after
            visual_recovery_result = None
            if (
                outcome.status != SUCCESS
                and not getattr(args, "no_visual_recovery", False)
            ):
                # A visual verification failure authorises only a bounded
                # re-observation. No route arbitration or execution can happen
                # on the failed outcome; the retry must pass the original chain.
                visual_recovery_result = _attempt_visual_recovery(
                    machine=visual_recovery_machine,
                    session=session,
                    ego=ego,
                    out_dir=out_dir,
                    args=args,
                    host_client=host_client,
                    host_planner=host_planner,
                    host_session_id=host_session_id,
                    host_context_revision=host_context_revision,
                    task_memory=task_memory,
                    round_index=round_index,
                    target=target,
                    route_goal_node_id=route.goal_node_id,
                    expected_node_id=expected_node_id,
                    excluded_nodes=other_parking_goals,
                    initial_outcome=outcome,
                    initial_frame=frame,
                    initial_state=state,
                    initial_image_path=image_path,
                    initial_image_sha=image_sha,
                    initial_image_size=image_size,
                    initial_observation=observation,
                    initial_request=request,
                    initial_planner_client=planner_client,
                    initial_intent_id=intent_id,
                    last_verified_identity=last_verified_identity,
                )
                round_result["visual_recovery"] = visual_recovery_result["recovery"]
                if visual_recovery_result["recovered"]:
                    round_result["initial_observation"] = {
                        **round_result["observation"]
                    }
                    outcome = visual_recovery_result["outcome"]
                    frame = visual_recovery_result["frame"]
                    state = visual_recovery_result["state"]
                    image_path = visual_recovery_result["image_path"]
                    image_sha = visual_recovery_result["image_sha"]
                    image_size = visual_recovery_result["image_size"]
                    observation = visual_recovery_result["observation"]
                    intent_id = visual_recovery_result["intent_id"]
                    pose = observation.pose
                    planner_client = visual_recovery_result["planner_client"]
                    request = visual_recovery_result["request"]
                    inference_started = visual_recovery_result[
                        "inference_started_utc"
                    ]
                    inference_finished = visual_recovery_result[
                        "inference_finished_utc"
                    ]
                    inference_wall_s = visual_recovery_result["inference_wall_s"]
                    round_result["observation"].update(
                        {
                            "image_path": image_path,
                            "image_sha256": image_sha,
                            "image_size_bytes": image_size,
                            "frame": frame.to_metadata(),
                            "state": state,
                            "pose": {
                                "x": pose.x,
                                "y": pose.y,
                                "heading": pose.heading,
                            },
                            "prompt": observation.prompt,
                            "prompt_sha256": observe01c.sha256_bytes(
                                observation.prompt.encode("utf-8")
                            ),
                            "intent_id": intent_id,
                            "target": target,
                            "recovered_from_frame_id": (
                                round_result["initial_observation"]["frame"][
                                    "frame_id"
                                ]
                            ),
                            "recovery_attempt": visual_recovery_result[
                                "recovery"
                            ]["attempt_count"],
                        }
                    )
                else:
                    # Recovery did not produce a verified decision. Keep the
                    # last real attempt's evidence, but never proceed to
                    # arbitration or execution.
                    outcome = visual_recovery_result["outcome"]
                    request = visual_recovery_result["request"]
                    planner_client = visual_recovery_result["planner_client"]
                    frame = visual_recovery_result["frame"]
                    state = visual_recovery_result["state"]
                    image_path = visual_recovery_result["image_path"]
                    image_sha = visual_recovery_result["image_sha"]
                    image_size = visual_recovery_result["image_size"]
                    observation = visual_recovery_result["observation"]
                    intent_id = visual_recovery_result["intent_id"]
                    pose = observation.pose
                    inference_started = visual_recovery_result[
                        "inference_started_utc"
                    ]
                    inference_finished = visual_recovery_result[
                        "inference_finished_utc"
                    ]
                    inference_wall_s = visual_recovery_result["inference_wall_s"]
            if planner_client is not None:
                updated_revision = planner_client.context_revision_after
                if isinstance(updated_revision, int):
                    host_context_revision = updated_revision
            if planner_client is not None and planner_client.last_exchange is not None:
                round_result["planner"] = (
                    planner_client.last_exchange.to_metadata()
                )
            round_result["request"] = request
            round_result["decision"] = outcome.to_metadata()
            if outcome.status == SUCCESS:
                last_verified_identity = outcome.directive.identified_as
            generation_s = request.get("generation_time")
            round_result["timing"].update(
                {
                    "model_started_utc": inference_started,
                    "model_finished_utc": inference_finished,
                    "model_wall_s": round(inference_wall_s, 3),
                    "model_generation_s": generation_s,
                    "model_http_and_client_overhead_s": (
                        None
                        if not isinstance(generation_s, (int, float))
                        else round(inference_wall_s - float(generation_s), 3)
                    ),
                }
            )
            if outcome.status != SUCCESS:
                round_result["status"] = outcome.status
                if outcome.status == MODEL_REQUEST_FAILED:
                    execution_error = True
                else:
                    decision_rejected = True
                result["stop"] = {
                    "stage": "decision",
                    "round": round_index,
                    "reason": outcome.status,
                    "error": {
                        "type": outcome.error_type,
                        "message": outcome.error_message,
                    },
                }
                if visual_recovery_result is not None:
                    result["stop"]["visual_recovery"] = (
                        visual_recovery_result["recovery"]
                    )
                    if not visual_recovery_result["recovered"]:
                        result["stop"]["visual_recovery_exhausted"] = True
                result["stm"]["records"].append(
                    _record_stm_round(
                        task_memory=task_memory,
                        round_result=round_result,
                        round_index=round_index,
                        task_target=target,
                        final_outcome=outcome,
                        execution=None,
                        outcome=(
                            RoundOutcome.FAILED_BEFORE_EXECUTION
                            if outcome.status == MODEL_REQUEST_FAILED
                            else RoundOutcome.REJECTED
                        ),
                        error=(
                            f"{outcome.status}: "
                            f"{outcome.error_type}: {outcome.error_message}"
                        ),
                    )
                )
                break

            arbitration_started_utc = utc_now()
            arbitration_started_monotonic = time.monotonic()
            blocked_edges = None
            if round_result.get("recovery"):
                recovery_node = (
                    round_result["recovery"].get("node_id") or expected_node_id
                )
                if recovery_node is not None:
                    blocked_edges, blocked_evidence = _blocked_candidate_edges(
                        recovery_node, route.goal_node_id, other_parking_goals
                    )
                    round_result["recovery_blocked_edges"] = blocked_evidence
                    result.setdefault("recovery_blocked_edges", []).append(
                        {
                            "round": round_index,
                            "node_id": recovery_node,
                            "blocked_edges": [
                                list(edge) for edge in sorted(blocked_edges)
                            ],
                            "evidence": blocked_evidence,
                        }
                    )
            arbitration = arbitrate_route(
                GRAPH,
                pose,
                outcome.directive,
                intent=outcome.intent,
                goal_node_id=route.goal_node_id,
                expected_node_id=expected_node_id,
                max_node_distance_m=MAX_NODE_DISTANCE_M,
                straight_tolerance_deg=STRAIGHT_TOLERANCE_DEG,
                turn_limit_deg=TURN_LIMIT_DEG,
                edge_ambiguity_tolerance_deg=EDGE_AMBIGUITY_DEG,
                safety_ok=True,
                invert_turn_direction=INVERT_TURN_DIRECTION,
                blocked_edges=blocked_edges,
                excluded_nodes=other_parking_goals,
            )
            round_result["arbitration"] = arbitration.to_metadata()
            arbitration_finished_utc = utc_now()
            round_result["timing"].update(
                {
                    "arbitration_started_utc": arbitration_started_utc,
                    "arbitration_finished_utc": arbitration_finished_utc,
                    "arbitration_s": round(
                        time.monotonic() - arbitration_started_monotonic, 3
                    ),
                }
            )
            execution_outcome = outcome
            execution_arbitration = arbitration
            redecision_selected = False
            if not may_drive(
                decision_status=outcome.status,
                arbitration_status=arbitration.status,
            ):
                redecision = None
                if (
                    not args.no_route_redecision
                    and outcome.status == SUCCESS
                    and arbitration.status
                    == RouteArbitrationStatus.NO_COMPATIBLE_ROUTE
                ):
                    # The original decision is preserved above. Stop first so
                    # the same frame is only reused when the vehicle is really
                    # stationary, then ask at most once.
                    session.brake_to_stop(ego, max_ticks=60)
                    pre_redecision_state = _state_metadata(session, ego, with_road=True)
                    history_note = _redecision_history_note(
                        previous_decision=previous_decision_summary,
                        previous_execution=previous_execution_summary,
                        previous_post_state=previous_post_state,
                        current_state=pre_redecision_state,
                        image_sha=image_sha,
                    )
                    redecision_intent_id = f"{intent_id}-redecision"
                    redecision_planner_client = None
                    if host_planner:
                        redecision_planner_client = HostPlannerModelClient(
                            host_client,
                            session_id=host_session_id,
                            context_revision=host_context_revision,
                            request_id_prefix=(
                                f"cap08b-replan-r{round_index}-"
                                f"{redecision_intent_id}"
                            ),
                            domain={
                                "capability": "planner.plan",
                                "parking": PARKING_CONTEXT,
                                "round": round_index,
                                "intent_id": redecision_intent_id,
                                "trigger": "no_compatible_route",
                                "original_decision_intent_id": intent_id,
                                "target": target,
                                "target_kind": args.target_kind,
                                "frame_id": observation.frame.frame_id,
                                "image_sha256": image_sha,
                                "pose": {
                                    "x": pre_redecision_state["x"],
                                    "y": pre_redecision_state["y"],
                                    "yaw": pre_redecision_state["yaw"],
                                },
                            },
                        )
                        redecision_model = redecision_planner_client
                    else:
                        # The longer route-facts prompt needs more generation
                        # budget than the normal round; with the normal 1800-token
                        # budget the real model returned an empty answer.
                        redecision_model = ServerImageModelClient(
                            backend=ZDTaichuServerBackend(
                                max_new_tokens=max(4096, args.max_new_tokens),
                                timeout=args.timeout,
                                temperature=0.0,
                                enable_thinking=args.enable_thinking,
                                stop=None if args.enable_thinking else ["</think>"],
                            )
                        )
                    calls, restore_opener = observe01c.install_request_recorder()
                    redecision_started = utc_now()
                    try:
                        redecision = run_route_redecision(
                            graph=GRAPH,
                            arbitration=arbitration,
                            original_outcome=outcome,
                            observation=observation,
                            goal_node_id=route.goal_node_id,
                            expected_identity=target,
                            intent_id=redecision_intent_id,
                            model=redecision_model,
                            instruction=args.instruction,
                            target_kind=args.target_kind,
                            target_note=target_note,
                            history_note=history_note,
                            current_state=pre_redecision_state,
                            stop_speed_mps=args.goal_stop_speed,
                            max_node_distance_m=MAX_NODE_DISTANCE_M,
                            straight_tolerance_deg=STRAIGHT_TOLERANCE_DEG,
                            turn_limit_deg=TURN_LIMIT_DEG,
                            edge_ambiguity_tolerance_deg=EDGE_AMBIGUITY_DEG,
                            invert_turn_direction=INVERT_TURN_DIRECTION,
                            blocked_edges=blocked_edges,
                            excluded_nodes=other_parking_goals,
                        )
                    finally:
                        if restore_opener is not None:
                            restore_opener()
                            restore_opener = None
                    redecision_finished = utc_now()
                    if redecision_planner_client is not None:
                        host_context_revision = (
                            redecision_planner_client.context_revision_after
                        )
                    redecision_meta = redecision.to_metadata()
                    redecision_meta["request"] = observe01c.request_evidence(
                        calls, image_sha
                    )
                    redecision_meta["request"][
                        "inference_started_utc"
                    ] = redecision_started
                    redecision_meta["request"][
                        "inference_finished_utc"
                    ] = redecision_finished
                    if redecision_planner_client is not None:
                        redecision_meta["request"][
                            "model_path"
                        ] = "kernel_planner_bridge"
                        exchange = redecision_planner_client.last_exchange
                        if exchange is not None:
                            redecision_meta["planner"] = exchange.to_metadata()
                            server_response = exchange.output.get(
                                "server_response"
                            )
                            if isinstance(server_response, dict):
                                redecision_meta["request"][
                                    "server_response_id"
                                ] = server_response.get("server_response_id")
                                redecision_meta["request"][
                                    "response_model"
                                ] = server_response.get("response_model")
                                redecision_meta["request"][
                                    "finish_reason"
                                ] = server_response.get("finish_reason")
                                redecision_meta["request"][
                                    "usage"
                                ] = server_response.get("usage")
                            redecision_meta["request"][
                                "planner_request_id"
                            ] = exchange.planner_request_id
                            redecision_meta["request"][
                                "planner_artifact_id"
                            ] = exchange.planning_artifact_id
                            redecision_meta["request"][
                                "planner_context_revision"
                            ] = exchange.context_revision
                    redecision_meta["pre_redecision_state"] = pre_redecision_state
                    redecision_meta["observation_frame_id"] = observation.frame.frame_id
                    redecision_meta["observation_image_sha256"] = image_sha
                    redecision_meta["original_decision_intent_id"] = intent_id
                    redecision_meta["redecision_intent_id"] = redecision_intent_id
                    round_result["redecision"] = redecision_meta

                    if redecision.selected:
                        execution_outcome = redecision.outcome
                        execution_arbitration = redecision.arbitration
                        redecision_selected = True
                        round_result[
                            "decision_redecision"
                        ] = execution_outcome.to_metadata()
                        round_result[
                            "arbitration_redecision"
                        ] = execution_arbitration.to_metadata()

                if not redecision_selected:
                    if redecision is None:
                        round_result["status"] = arbitration.status
                        decision_rejected = True
                        result["stop"] = {
                            "stage": "arbitration",
                            "round": round_index,
                            "reason": arbitration.status,
                            "detail": arbitration.reason,
                        }
                        stop_reason = arbitration.status
                    else:
                        round_result["status"] = redecision.status
                        if redecision.status in (
                            MODEL_REQUEST_FAILED,
                            RouteRedecisionStatus.ERROR,
                        ):
                            execution_error = True
                        elif redecision.status in (
                            RouteRedecisionStatus.NOT_STOPPED,
                            RouteRedecisionStatus.OBSERVATION_STALE,
                        ):
                            safety_stopped = True
                        else:
                            decision_rejected = True
                        result["stop"] = {
                            "stage": "redecision",
                            "round": round_index,
                            "reason": redecision.status,
                            "detail": redecision.reason,
                            "original_arbitration": arbitration.status,
                        }
                        stop_reason = redecision.status
                    session.brake_to_stop(ego, max_ticks=60)
                    round_result["execution"] = {
                        "executed": False,
                        "post_state": _state_metadata(session, ego, with_road=True),
                        "stop_reason": stop_reason,
                    }
                    round_result["timing"].update(
                        {
                            "execution_started_utc": utc_now(),
                            "execution_finished_utc": utc_now(),
                            "execution_s": 0.0,
                            "round_wall_s": round(
                                time.monotonic() - round_started_monotonic, 3
                            ),
                        }
                    )
                    previous_execution_finished_monotonic = time.monotonic()
                    if redecision is None:
                        stm_outcome = RoundOutcome.REJECTED
                    elif redecision.status in (
                        MODEL_REQUEST_FAILED,
                        RouteRedecisionStatus.ERROR,
                        RouteRedecisionStatus.NOT_STOPPED,
                        RouteRedecisionStatus.OBSERVATION_STALE,
                        RouteRedecisionStatus.CONTEXT_UNAVAILABLE,
                    ):
                        stm_outcome = RoundOutcome.FAILED_BEFORE_EXECUTION
                    else:
                        stm_outcome = RoundOutcome.REJECTED
                    result["stm"]["records"].append(
                        _record_stm_round(
                            task_memory=task_memory,
                            round_result=round_result,
                            round_index=round_index,
                            task_target=target,
                            final_outcome=(
                                redecision.outcome
                                if redecision is not None
                                else outcome
                            ),
                            execution=round_result["execution"],
                            outcome=stm_outcome,
                            error=(
                                f"{stop_reason}: "
                                f"{(result.get('stop') or {}).get('detail')}"
                            ),
                        )
                    )
                    break

            if (
                getattr(args, "obstacle_round", 0)
                and round_index == int(args.obstacle_round)
                and not result.get("obstacle_injection")
            ):
                injection = {
                    "round": round_index,
                    "model_direction": (
                        None
                        if execution_outcome.directive is None
                        else execution_outcome.directive.direction
                    ),
                    "selected_edge": list(
                        execution_arbitration.selected_edge or ()
                    ),
                    "route_node_ids": list(
                        execution_arbitration.route_node_ids
                    ),
                    "observation_frame_id": frame.frame_id,
                    "injected_utc": utc_now(),
                    "obstacles": [],
                }
                injection["obstacles"].append(
                    _spawn_demo_obstacle(
                        session,
                        world,
                        args.obstacle_blueprint,
                        args.obstacle_x,
                        args.obstacle_y,
                        args.obstacle_z,
                        args.obstacle_yaw,
                        "primary",
                    )
                )
                if (
                    getattr(args, "obstacle2_x", None) is not None
                    and getattr(args, "obstacle2_y", None) is not None
                ):
                    injection["obstacles"].append(
                        _spawn_demo_obstacle(
                            session,
                            world,
                            args.obstacle_blueprint,
                            args.obstacle2_x,
                            args.obstacle2_y,
                            args.obstacle_z,
                            args.obstacle_yaw,
                            "secondary",
                        )
                    )
                result["obstacle_injection"] = injection
                result.setdefault("obstacles", []).extend(
                    injection["obstacles"]
                )
                round_result["obstacle_injection"] = injection

            if (
                getattr(args, "mid_obstacle_round", 0)
                and round_index == int(args.mid_obstacle_round)
                and execution_arbitration.selected_edge
            ):
                edge = tuple(args.mid_obstacle_edge)
                route_ids = list(execution_arbitration.route_node_ids)
                route_points = list(execution_arbitration.route_points)
                cum = cumulative_lengths(route_points)
                arm = next(
                    (
                        index
                        for index in range(len(route_ids) - 1)
                        if {route_ids[index], route_ids[index + 1]}
                        == set(edge)
                    ),
                    None,
                )
                if arm is None:
                    result["mid_obstacle_trigger"] = {
                        "armed": False,
                        "reason": "edge not on the selected execution route",
                        "edge": list(edge),
                        "route_node_ids": route_ids,
                    }
                else:
                    prefix = GRAPH.points(route_ids[: arm + 1])
                    edge_start_s = cumulative_lengths(prefix)[-1]
                    cone_s = min(
                        cum[-1], edge_start_s + float(args.mid_obstacle_edge_s)
                    )
                    trigger_s = edge_start_s + float(
                        args.mid_obstacle_trigger_edge_s
                    )
                    cone_point = point_at_s(route_points, cum, cone_s)
                    tangent_point = point_at_s(
                        route_points, cum, min(cum[-1], cone_s + 0.2)
                    )
                    cone_yaw = math.degrees(
                        math.atan2(
                            tangent_point[1] - cone_point[1],
                            tangent_point[0] - cone_point[0],
                        )
                    ) + float(args.mid_obstacle_yaw_offset_deg)
                    trigger = {
                        "label": "secondary_mid",
                        "blueprint": args.mid_obstacle_blueprint,
                        "x": round(cone_point[0], 3),
                        "y": round(cone_point[1], 3),
                        "z": float(args.mid_obstacle_z),
                        "yaw_deg": round(cone_yaw, 3),
                        "edge": list(edge),
                        "edge_start_s": round(edge_start_s, 3),
                        "cone_s": round(cone_s, 3),
                        "trigger_s": round(trigger_s, 3),
                        "route_node_ids": route_ids,
                        "armed_utc": utc_now(),
                        "spawned": False,
                    }
                    _RUN_OBSTACLE_TRIGGERS.append(trigger)
                    result["mid_obstacle_trigger"] = dict(trigger)
                    round_result["mid_obstacle_trigger"] = dict(trigger)

            segment_override = None
            selected_to = None
            if execution_arbitration.selected_edge:
                selected_to = execution_arbitration.selected_edge[1]
            if selected_to in RECOVERY_ENTRY_NODE_IDS:
                segment_override = args.segment_nodes
                args.segment_nodes = max(
                    args.segment_nodes,
                    len(execution_arbitration.route_node_ids) - 1,
                )
                round_result["recovery_segment_override"] = {
                    "from": segment_override,
                    "to": args.segment_nodes,
                    "target_node_id": (
                        execution_arbitration.route_node_ids[-1]
                    ),
                }

            round_video = None
            if getattr(args, "video_dir", None):
                round_video = VideoRecorder(
                    session,
                    ego,
                    Path(args.video_dir) / f"round_{round_index:02d}",
                    fov=round_fov,
                    width=int(args.video_width),
                    height=int(args.video_height),
                    sensor_tick=1.0 / max(1.0, float(args.video_fps)),
                )
                active_round_video = round_video
            execution_started_utc = utc_now()
            execution_started_monotonic = time.monotonic()
            if kernel_exe:
                execution = _execute_segment_via_kernel(
                    session,
                    ego,
                    execution_arbitration,
                    args,
                    round_index,
                    execution_outcome.directive.direction,
                    execution_outcome.intent.intent_id,
                    host_client,
                    bridge,
                    host_session_id=host_session_id,
                    host_context_revision=host_context_revision,
                )
                kernel_response = (execution.get("kernel") or {}).get(
                    "response"
                ) or {}
                if isinstance(
                    kernel_response.get("context_revision"), int
                ):
                    host_context_revision = kernel_response["context_revision"]
            else:
                execution = _drive_segment(
                    session,
                    ego,
                    execution_arbitration,
                    args,
                    round_index,
                    execution_outcome.directive.direction,
                )
                execution["executed"] = True
            execution_finished_utc = utc_now()
            execution_finished_monotonic = time.monotonic()
            execution["timing"] = {
                "started_utc": execution_started_utc,
                "finished_utc": execution_finished_utc,
                "wall_s": round(
                    execution_finished_monotonic - execution_started_monotonic, 3
                ),
            }
            round_result["timing"].update(
                {
                    "execution_started_utc": execution_started_utc,
                    "execution_finished_utc": execution_finished_utc,
                    "execution_s": execution["timing"]["wall_s"],
                    "stop_to_execution_s": (
                        None
                        if previous_execution_finished_monotonic is None
                        else round(
                            execution_started_monotonic
                            - previous_execution_finished_monotonic,
                            3,
                        )
                    ),
                }
            )
            previous_execution_finished_monotonic = execution_finished_monotonic
            if redecision_selected:
                selected_route = list(
                    execution_arbitration.selected_route_node_ids
                )
                executed_route_ids = list(execution.get("route_node_ids") or [])
                execution["redecision"] = {
                    "selected_edge": list(execution_arbitration.selected_edge),
                    "selected_route_node_ids": selected_route,
                    "execution_target_node_id": execution.get("target_node_id"),
                    "execution_route_node_ids": executed_route_ids,
                    "execution_target_on_selected_route": (
                        execution.get("target_node_id") in selected_route
                        and executed_route_ids == selected_route
                    ),
                }
                round_result["redecision"][
                    "execution_linkage"
                ] = execution["redecision"]
            round_result["execution"] = execution
            round_result["kernel"] = execution.get("kernel")
            mid_records = [
                record
                for record in _RUN_OBSTACLE_RECORDS
                if record.get("phase") == "mid_segment"
                and record not in result.get("obstacles", [])
            ]
            if mid_records:
                round_result.setdefault("mid_segment_obstacles", []).extend(
                    mid_records
                )
                result.setdefault("obstacles", []).extend(mid_records)
                armed = result.get("mid_obstacle_trigger")
                if isinstance(armed, dict):
                    armed["spawned"] = True
                    armed["spawned_frames"] = [
                        record["injected_frame"] for record in mid_records
                    ]
                    armed["spawned_actor_ids"] = [
                        record["actor_id"] for record in mid_records
                    ]
                    armed["spawned_utc"] = utc_now()
            if segment_override is not None:
                args.segment_nodes = segment_override
                segment_override = None
            if round_video is not None:
                round_result["video"] = round_video.close()
                round_video = None
                active_round_video = None
            result["stm"]["records"].append(
                _record_stm_round(
                    task_memory=task_memory,
                    round_result=round_result,
                    round_index=round_index,
                    task_target=target,
                    final_outcome=execution_outcome,
                    execution=execution,
                    outcome=_stm_outcome_for_execution(execution),
                    error=(
                        None
                        if execution.get("segment_success") is True
                        else f"segment stop_reason={execution.get('stop_reason')}"
                    ),
                )
            )
            if "recovery" in round_result:
                recovery_meta = round_result["recovery"]
                recovery_meta["observation_frame_id"] = frame.frame_id
                recovery_meta["observation_image_sha256"] = image_sha
                recovery_meta["selected_edge"] = list(
                    execution_arbitration.selected_edge or ()
                )
                recovery_meta["selected_route_node_ids"] = list(
                    execution_arbitration.route_node_ids
                )
                recovery_meta["route_changed"] = (
                    recovery_meta["selected_edge"]
                    != recovery_meta["failed_selected_edge"]
                )
                recovery_meta["executed"] = execution.get("executed")
                recovery_meta["moved_m"] = execution.get("moved_m")
                recovery_meta["segment_success"] = execution.get(
                    "segment_success"
                )
                recovery_meta["kernel_execution_status"] = (
                    (execution.get("kernel") or {}).get("response") or {}
                ).get("execution_status")
                # The evidence ledger holds a copy of the pending recovery.
                # Backfill it so every recovery (not only the one that reaches
                # the goal) carries its real observation/selection/execution.
                for item in result.get("recoveries", []):
                    if item.get("after_round") == recovery_meta.get("after_round"):
                        for key in (
                            "observation_frame_id",
                            "observation_image_sha256",
                            "selected_edge",
                            "selected_route_node_ids",
                            "route_changed",
                            "executed",
                            "moved_m",
                            "segment_success",
                            "kernel_execution_status",
                        ):
                            item[key] = recovery_meta.get(key)
            expected_node_id = execution["target_node_id"]
            previous_post_state = execution["post_state"]
            previous_frame_sha = image_sha
            kernel_response = (execution.get("kernel") or {}).get("response") or {}
            previous_execution_summary = {
                "target_node_id": execution.get("target_node_id"),
                "moved_m": execution.get("moved_m"),
                "stop_reason": execution.get("stop_reason"),
                "segment_success": execution.get("segment_success"),
                "kernel_execution_status": kernel_response.get("execution_status"),
            }
            previous_decision_summary = {
                "position": (
                    None
                    if execution_outcome.decision is None
                    else execution_outcome.decision.position
                ),
                "direction": execution_outcome.directive.direction,
                "evidence": (
                    None
                    if execution_outcome.decision is None
                    else execution_outcome.decision.evidence
                ),
                "redecision": redecision_selected,
            }

            post_state = execution["post_state"]
            goal_eval = evaluate_goal(
                goal_spec,
                VehiclePose(
                    x=post_state["x"],
                    y=post_state["y"],
                    heading=math.radians(post_state["yaw"]),
                ),
                speed_mps=post_state["speed"],
                stopped=execution["stopped"],
            )
            round_result["goal_evaluation"] = goal_eval.to_metadata()
            execution["goal_reached"] = goal_eval.ok
            round_result["timing"].update(
                {
                    "finished_utc": utc_now(),
                    "round_wall_s": round(
                        time.monotonic() - round_started_monotonic, 3
                    ),
                }
            )

            if goal_eval.ok and execution["segment_success"]:
                round_result["status"] = TaskStatus.GOAL_REACHED
                if "recovery" in round_result:
                    round_result["recovery"]["goal_reached"] = True
                    for item in result.get("recoveries", []):
                        if item.get("after_round") == round_result["recovery"].get(
                            "after_round"
                        ):
                            item["goal_reached"] = True
                            item["observation_frame_id"] = round_result[
                                "recovery"
                            ].get("observation_frame_id")
                            item["executed"] = round_result["recovery"].get(
                                "executed"
                            )
                            item["route_changed"] = round_result["recovery"].get(
                                "route_changed"
                            )
                            item["recovery_selected_edge"] = round_result[
                                "recovery"
                            ].get("selected_edge")
                            item["recovery_route_changed"] = round_result[
                                "recovery"
                            ].get("route_changed")
                            item["recovery_executed"] = round_result[
                                "recovery"
                            ].get("executed")
                goal_reached = True
                result["stop"] = {
                    "stage": "goal",
                    "round": round_index,
                    "reason": "goal_reached",
                    "detail": (
                        f"distance={goal_eval.distance_m:.3f} m, "
                        f"heading_error={math.degrees(goal_eval.heading_error_rad):.3f} deg, "
                        f"speed={post_state['speed']:.3f} m/s"
                    ),
                }
                break

            if not execution["segment_success"]:
                round_result["status"] = "segment_failed"
                reason = execution["stop_reason"]
                post_motion = execution.get("executed") is True
                recovery_node_id = execution_arbitration.matched_node_id
                recovery_node_distance = (
                    execution_arbitration.matched_node_distance_m
                )
                recovery_node_error = None
                if post_motion:
                    (
                        recovery_node_id,
                        recovery_node_distance,
                        recovery_node_error,
                    ) = _nearest_recovery_node(execution.get("post_state"))
                recovery_heading_rad = None
                for state_key in ("post_state", "pre_state"):
                    candidate_state = execution.get(state_key)
                    if (
                        isinstance(candidate_state, dict)
                        and "yaw" in candidate_state
                    ):
                        recovery_heading_rad = math.radians(
                            float(candidate_state["yaw"])
                        )
                        break
                # Fresh real clearance evidence at the stop node: the same
                # check the next arbitration would use. Its absence is treated
                # as unknown evidence, never as proof of safety.
                recovery_blocked_edges = None
                recovery_blocked_evidence: list = []
                blocking_evidence_status = "unavailable"
                if recovery_node_id is not None:
                    try:
                        (
                            recovery_blocked_edges,
                            recovery_blocked_evidence,
                        ) = _blocked_candidate_edges(
                            recovery_node_id,
                            route.goal_node_id,
                            other_parking_goals,
                        )
                        blocking_evidence_status = "fresh"
                        result.setdefault(
                            "recovery_blocked_edges", []
                        ).append(
                            {
                                "round": round_index,
                                "stage": "recovery_gate",
                                "node_id": recovery_node_id,
                                "blocked_edges": [
                                    list(edge)
                                    for edge in sorted(recovery_blocked_edges)
                                ],
                                "evidence": recovery_blocked_evidence,
                            }
                        )
                    except Exception as exc:  # evidence unavailable, not "clear"
                        recovery_blocked_edges = None
                        recovery_blocked_evidence = [
                            {"error": f"{type(exc).__name__}: {exc}"}
                        ]
                forward_candidates = ()
                candidates_error = None
                if (
                    recovery_node_id is not None
                    and recovery_heading_rad is not None
                ):
                    try:
                        forward_candidates = _forward_candidates(
                            recovery_node_id,
                            route.goal_node_id,
                            recovery_heading_rad,
                            blocked_edges=recovery_blocked_edges,
                            excluded_nodes=other_parking_goals,
                        )
                    except Exception as exc:
                        candidates_error = f"{type(exc).__name__}: {exc}"
                failed_edge = tuple(
                    execution_arbitration.selected_edge or ()
                )
                skill_result = evaluate_navigation_recovery(
                    RecoverySkillInput(
                        goal_node_id=route.goal_node_id,
                        observation_frame_id=frame.frame_id,
                        observation_image_sha256=image_sha,
                        stop_reason=reason,
                        executed=execution.get("executed"),
                        stopped=execution.get("stopped"),
                        goal_reached=goal_eval.ok,
                        matched_node_id=recovery_node_id,
                        candidates=forward_candidates,
                        failed_edge=failed_edge or None,
                        blocking_evidence=blocking_evidence_status,
                        attempts=recovery_attempts,
                        max_attempts=args.max_recovery_attempts,
                        recovery_enabled=bool(args.recover_after_safety_stop),
                    )
                )
                recovery_decision = skill_result.decision
                forward_count = skill_result.forward_candidates
                blocked_count = skill_result.blocked_candidates
                eligible_count = skill_result.eligible_candidates
                round_result["recovery_skill"] = skill_result.to_metadata()
                round_result["recovery_candidates"] = {
                    "node_id": recovery_node_id,
                    "heading_deg": (
                        None
                        if recovery_heading_rad is None
                        else round(math.degrees(recovery_heading_rad), 3)
                    ),
                    "observed_frame": frame.frame_id,
                    "observed_utc": utc_now(),
                    "failed_edge": list(failed_edge),
                    "blocking_evidence": blocking_evidence_status,
                    "evidence_error": candidates_error,
                    "forward_candidates": forward_count,
                    "blocked_candidates": blocked_count,
                    "eligible_candidates": eligible_count,
                    "candidates": [
                        {
                            "edge": [
                                candidate.from_node_id,
                                candidate.to_node_id,
                            ],
                            "turn_class": candidate.turn_class,
                            "reachable": candidate.reachable,
                            "blocked": candidate.blocked,
                            "route_node_ids": list(candidate.route_node_ids),
                        }
                        for candidate in forward_candidates
                    ],
                    "blocked_evidence": recovery_blocked_evidence,
                }
                goal_reachable_candidates = forward_count
                round_result["recovery_node"] = {
                    "post_motion": post_motion,
                    "node_id": recovery_node_id,
                    "distance_m": (
                        None
                        if recovery_node_distance is None
                        else round(float(recovery_node_distance), 3)
                    ),
                    "error": recovery_node_error,
                    "goal_reachable_candidates": goal_reachable_candidates,
                    "forward_candidates": forward_count,
                    "blocked_candidates": blocked_count,
                    "eligible_candidates": eligible_count,
                    "blocking_evidence": blocking_evidence_status,
                }
                round_result["recovery_policy"] = (
                    None
                    if recovery_decision is None
                    else recovery_decision.to_metadata()
                )
                if recovery_decision is not None and recovery_decision.allowed:
                    recovery_attempts += 1
                    pending_recovery = {
                        "after_round": round_index,
                        "trigger": recovery_decision.trigger,
                        "node_id": recovery_node_id,
                        "node_match_distance_m": (
                            None
                            if recovery_node_distance is None
                            else round(float(recovery_node_distance), 3)
                        ),
                        "failed_stop_reason": reason,
                        "failed_moved_m": execution.get("moved_m"),
                        "failed_frame_id": frame.frame_id,
                        "failed_image_sha256": image_sha,
                        "failed_selected_edge": list(
                            execution_arbitration.selected_edge or ()
                        ),
                        "failed_route_node_ids": list(
                            execution_arbitration.route_node_ids
                        ),
                        "failed_target_node_id": execution.get("target_node_id"),
                        "pre_state": execution.get("pre_state"),
                        "post_state": execution.get("post_state"),
                        "new_observation_required": True,
                        "policy": recovery_decision.to_metadata(),
                        "note": (
                            "the vehicle really moved and then stopped at a "
                            "real obstruction; re-observe at the nearest graph "
                            "node and choose a different legal edge"
                            if post_motion
                            else (
                                "the vehicle did not execute the blocked "
                                "segment; re-observe and choose a different "
                                "legal edge"
                            )
                        ),
                    }
                    result.setdefault("recoveries", []).append(
                        dict(pending_recovery)
                    )
                    round_result["status"] = "recovery_pending"
                    round_result["recovery_pending"] = dict(pending_recovery)
                    result["stop"] = None
                    # The next arbitration must stay at the real current node:
                    # the failed segment's start node when no motion happened,
                    # and the nearest node to the post-stop pose otherwise.
                    expected_node_id = recovery_node_id
                    previous_post_state = execution["post_state"]
                    previous_frame_sha = image_sha
                    previous_execution_summary = {
                        "target_node_id": execution.get("target_node_id"),
                        "moved_m": execution.get("moved_m"),
                        "stop_reason": reason,
                        "segment_success": False,
                        "kernel_execution_status": kernel_response.get(
                            "execution_status"
                        ),
                    }
                    previous_decision_summary = {
                        "position": (
                            None
                            if execution_outcome.decision is None
                            else execution_outcome.decision.position
                        ),
                        "direction": execution_outcome.directive.direction,
                        "evidence": (
                            None
                            if execution_outcome.decision is None
                            else execution_outcome.decision.evidence
                        ),
                        "redecision": False,
                    }
                    continue
                if reason == "timeout":
                    timed_out = True
                elif reason in (
                    "kernel_transport_failed",
                    "kernel_validation_failed",
                    "controller_exception",
                ):
                    execution_error = True
                else:
                    safety_stopped = True
                result["stop"] = {
                    "stage": "execution",
                    "round": round_index,
                    "reason": reason,
                    "detail": (
                        f"distance_to_target_m={execution.get('distance_to_target_m')}, "
                        f"stopped={execution['stopped']}, "
                        f"executed={execution.get('executed')}"
                    ),
                }
                break

            round_result["status"] = TaskStatus.RUNNING
            if time.monotonic() - task_started_monotonic > args.max_total_wall_seconds:
                timed_out = True
                result["stop"] = {
                    "stage": "task",
                    "round": round_index,
                    "reason": "max_total_wall_seconds",
                    "detail": f"limit={args.max_total_wall_seconds} s",
                }
                break
        else:
            max_rounds = True
            result["stop"] = {
                "stage": "task",
                "reason": "max_rounds",
                "detail": f"{args.rounds} rounds exhausted without goal_reached",
            }

        # A final real stop + state read, even after a model/arbitration refusal.
        if ego is not None:
            session.brake_to_stop(ego, max_ticks=80)
        result["final_state"] = (
            _state_metadata(session, ego, with_road=True) if ego is not None else None
        )
        final_goal = None
        if ego is not None:
            final_state = result["final_state"]
            final_goal = evaluate_goal(
                goal_spec,
                VehiclePose(
                    x=final_state["x"],
                    y=final_state["y"],
                    heading=math.radians(final_state["yaw"]),
                ),
                speed_mps=final_state["speed"],
                stopped=final_state["speed"] < args.goal_stop_speed,
            )
            result["final_goal_evaluation"] = final_goal.to_metadata()
        if ego is not None and getattr(args, "final_photo_dir", None):
            try:
                result["final_photo"] = _capture_final_photo(
                    session, args.final_photo_dir
                )
            except Exception as exc:
                result["final_photo_error"] = f"{type(exc).__name__}: {exc}"

        # The independent bay-03 verdict is the authority on parking success.
        # A model ``completed`` field, a Kernel ``completed`` status, or the
        # loose goal radius below cannot substitute for this real-state check.
        parking_verdict = None
        parking_stable = None
        if SCENARIO == "carpark_parking" and ego is not None and not approach_only:
            parking_stable = _stable_parking_stop(session, ego)
            result["parking_stable_stop"] = parking_stable
            result["final_state"] = parking_stable["final_state"]
            result["collision_events"] = _collision_snapshot()
            last_round = result["rounds"][-1] if result["rounds"] else {}
            last_execution = last_round.get("execution") or {}
            last_kernel = (last_round.get("kernel") or {}).get("response") or {}
            safety_reason = last_execution.get("stop_reason")
            if (
                last_execution.get("target_node_id")
                not in PARKING_GOAL_NODES
            ):
                safety_reason = "parking_phase_not_reached"
            goal_node_id = (result.get("goal_spec") or {}).get("node_id")
            bay_spec = PARKING_GOAL_SPECS.get(goal_node_id)
            if bay_spec is None:
                raise RuntimeError(
                    f"no parking bay spec for goal node {goal_node_id!r}"
                )
            parking_verdict = evaluate_parking_verdict(
                target_node_id=goal_node_id,
                target_bay_id=bay_spec["bay_id"],
                slot_node_id=goal_node_id,
                bay_id=bay_spec["bay_id"],
                bay_polygon=bay_spec["bay_polygon"],
                bay_center=bay_spec["bay_center"],
                x=parking_stable["final_state"]["x"],
                y=parking_stable["final_state"]["y"],
                yaw_rad=math.radians(parking_stable["final_state"]["yaw"]),
                speed_mps=parking_stable["max_speed_mps"],
                stop_stable=parking_stable["stable"],
                stable_position_drift_m=parking_stable["position_drift_m"],
                collision_count=len(result["collision_events"]),
                safety_stop_reason=safety_reason,
                kernel_execution_status=last_kernel.get("execution_status"),
            )
            result["parking_verdict"] = parking_verdict.to_metadata()
            if not parking_verdict.ok:
                goal_reached = False
                result["stop"] = {
                    "stage": "parking_verdict",
                    "reason": "parking_not_confirmed",
                    "detail": ", ".join(parking_verdict.reasons),
                }
                task_status = TaskStatus.PARKING_NOT_CONFIRMED
            else:
                goal_reached = True
                task_status = resolve_task_status(
                    goal_reached=True,
                    decision_rejected=decision_rejected,
                    safety_stopped=safety_stopped,
                    timed_out=timed_out,
                    max_rounds=max_rounds,
                    execution_error=execution_error,
                )
        else:
            task_status = resolve_task_status(
                goal_reached=goal_reached,
                decision_rejected=decision_rejected,
                safety_stopped=safety_stopped,
                timed_out=timed_out,
                max_rounds=max_rounds,
                execution_error=execution_error,
            )
            if approach_only and ego is not None:
                result["collision_events"] = _collision_snapshot()
                result["target_approach_kernel_executions"] = sum(
                    1
                    for item in result["rounds"]
                    if ((item.get("execution") or {}).get("kernel"))
                )
                last_round = result["rounds"][-1] if result["rounds"] else {}
                last_kernel = (
                    (last_round.get("execution") or {}).get("kernel") or {}
                ).get("response") or {}
                if final_goal is None:
                    result["target_approach_verdict"] = {
                        "ok": False,
                        "reasons": ["missing_final_goal_evaluation"],
                    }
                    goal_reached = False
                    task_status = TaskStatus.TARGET_APPROACH_NOT_CONFIRMED
                    result["stop"] = {
                        "stage": "target_approach",
                        "reason": "target_approach_not_confirmed",
                        "detail": "missing_final_goal_evaluation",
                    }
                else:
                    approach_verdict = evaluate_target_approach(
                        task_id=args.task_id,
                        binding=binding_artifact,
                        approach_node_id=goal_spec.node_id,
                        goal_evaluation=final_goal,
                        target_id=args.target_id,
                        collision_count=len(result["collision_events"]),
                        kernel_execution_status=last_kernel.get(
                            "execution_status"
                        ),
                    )
                    result["target_approach_verdict"] = (
                        approach_verdict.to_metadata()
                    )
                    if not approach_verdict.ok:
                        goal_reached = False
                        task_status = TaskStatus.TARGET_APPROACH_NOT_CONFIRMED
                        result["stop"] = {
                            "stage": "target_approach",
                            "reason": "target_approach_not_confirmed",
                            "detail": ", ".join(approach_verdict.reasons),
                        }
        result["task_status"] = task_status
        task_memory.mark_stopped(task_status)
        result["stm"]["final"] = {
            "stop_reason": task_memory.stop_reason,
            "records": len(task_memory.records),
            "next_round_index": task_memory.next_round_index,
            "context": task_memory.render_compact_context(max_chars=2400),
            "context_full": task_memory.render_context(),
        }
        result["meta"]["task_finished_utc"] = utc_now()
        result["meta"]["task_wall_seconds"] = round(
            time.monotonic() - task_started_monotonic, 3
        )

        rounds = result["rounds"]
        # A real model round is one whose evidence carries the model server's
        # own response identity. The direct HTTP path records http_status=200;
        # the Kernel planner path records the bridge-forwarded server response
        # and has no in-process HTTP status.
        def _real_model_response(item: dict) -> bool:
            request_evidence = item.get("request") or {}
            return bool(
                request_evidence.get("server_response_id")
                and request_evidence.get("http_status") in (None, 200)
            )

        real_model_rounds = sum(
            1 for item in rounds if _real_model_response(item)
        )
        successful_segments = sum(
            1
            for item in rounds
            if (item.get("execution") or {}).get("segment_success") is True
        )
        total_motion_m = round(
            sum(
                float((item.get("execution") or {}).get("moved_m") or 0.0)
                for item in rounds
            ),
            3,
        )
        distinct_frames = len({item["observation"]["image_sha256"] for item in rounds})
        frame_ids = [item["observation"]["frame"]["frame_id"] for item in rounds]
        kernel_rounds = sum(
            1
            for item in rounds
            if (item.get("kernel") or {}).get("called") is True
            and ((item.get("kernel") or {}).get("response") or {}).get(
                "execution_status"
            )
            == "completed"
        )
        redecision_rounds = [
            item.get("redecision") or {}
            for item in rounds
            if (item.get("redecision") or {}).get("attempted") is True
        ]
        redecision_selected_rounds = [
            item for item in redecision_rounds if item.get("selected") is True
        ]
        result["summary"] = {
            "route_name": route_name,
            "start_node": route.start_node_id,
            "goal_node": route.goal_node_id,
            "planned_path": list(route.path),
            "path_length_m": round(route.length_m, 3),
            "attempted_rounds": len(rounds),
            "real_model_rounds": real_model_rounds,
            "successful_segments": successful_segments,
            "total_motion_m": total_motion_m,
            "kernel_rounds": kernel_rounds,
            "redecision_attempted": len(redecision_rounds),
            "redecision_selected": len(redecision_selected_rounds),
            "redecision_statuses": [
                item.get("status") for item in redecision_rounds
            ],
            "recovery_attempts": len(result.get("recoveries", [])),
            "recovery_successes": sum(
                1
                for item in result.get("recoveries", [])
                if item.get("goal_reached") is True
            ),
            "stm_task_id": task_memory.task_id,
            "stm_records": len(task_memory.records),
            "stm_history_rounds": sum(
                1
                for item in rounds
                if (item.get("observation") or {}).get("history_context_used")
                is True
            ),
            "stm_stop_reason": task_memory.stop_reason,
            "distinct_observations": distinct_frames,
            "frame_ids": frame_ids,
            "final_task_status": task_status,
            "final_goal_distance_m": (
                None if final_goal is None else round(final_goal.distance_m, 3)
            ),
            "final_goal_heading_error_deg": (
                None
                if final_goal is None
                else round(math.degrees(final_goal.heading_error_rad), 3)
            ),
            "final_goal_reasons": (
                [] if final_goal is None else list(final_goal.reasons)
            ),
        }
        latency_rows = []
        for item in rounds:
            timing = item.get("timing") or {}
            decision = item.get("decision") or {}
            latency_rows.append(
                {
                    "round": item.get("round"),
                    "started_utc": timing.get("started_utc"),
                    "finished_utc": timing.get("finished_utc"),
                    "observation_s": timing.get("observation_s"),
                    "model_wall_s": timing.get("model_wall_s"),
                    "model_generation_s": timing.get("model_generation_s"),
                    "model_http_and_client_overhead_s": timing.get(
                        "model_http_and_client_overhead_s"
                    ),
                    "decision_parse_s": (
                        None
                        if not isinstance(decision.get("total_duration_seconds"), (int, float))
                        or not isinstance(decision.get("model_duration_seconds"), (int, float))
                        else round(
                            float(decision["total_duration_seconds"])
                            - float(decision["model_duration_seconds"]),
                            3,
                        )
                    ),
                    "arbitration_s": timing.get("arbitration_s"),
                    "execution_s": timing.get("execution_s"),
                    "round_wall_s": timing.get("round_wall_s"),
                    "stop_to_execution_s": timing.get("stop_to_execution_s"),
                    "observation_frame_id": (
                        (item.get("observation") or {}).get("frame") or {}
                    ).get("frame_id"),
                    "model_direction": (
                        (item.get("decision") or {}).get("directive") or {}
                    ).get("direction"),
                    "selected_edge": (
                        (item.get("arbitration") or {}).get("selected_edge")
                    ),
                    "executed": (
                        (item.get("execution") or {}).get("executed")
                    ),
                    "stop_reason": (
                        (item.get("execution") or {}).get("stop_reason")
                    ),
                }
            )
        result["latency"] = {
            "clock": "wall",
            "rows": latency_rows,
            "totals": {
                "task_wall_s": result["meta"].get("task_wall_seconds"),
                "model_wall_s": round(
                    sum(
                        float(row["model_wall_s"] or 0.0)
                        for row in latency_rows
                    ),
                    3,
                ),
                "execution_s": round(
                    sum(
                        float(row["execution_s"] or 0.0)
                        for row in latency_rows
                    ),
                    3,
                ),
                "round_wall_s": round(
                    sum(
                        float(row["round_wall_s"] or 0.0)
                        for row in latency_rows
                    ),
                    3,
                ),
            },
            "not_separately_measured": [
                "Kernel authorization versus CARLA driving inside execution_s",
                "Taichu GPU kernel time; generation_time is the server-reported "
                "generation duration, not a GPU profile",
                "CARLA rendering time inside observation_s",
            ],
        }
        checks = [
            {
                "name": "goal_reached",
                "pass": task_status == TaskStatus.GOAL_REACHED,
            },
            {
                "name": "at_least_one_real_model_round",
                "pass": real_model_rounds >= 1,
            },
            {
                "name": "all_rounds_have_a_real_model_request",
                "pass": real_model_rounds == len(rounds),
            },
            {
                "name": "all_rounds_distinct_observations",
                "pass": distinct_frames == len(rounds)
                and len(set(frame_ids)) == len(frame_ids),
            },
            {
                "name": "all_rounds_link_previous_post_state",
                "pass": all(
                    rounds[index]["linkage"][
                        "pre_state_matches_previous_post_state"
                    ]
                    is True
                    for index in range(1, len(rounds))
                ),
            },
            {
                "name": "all_rounds_new_image",
                "pass": all(
                    rounds[index]["linkage"]["frame_changed"] is True
                    for index in range(1, len(rounds))
                ),
            },
            {
                "name": "model_requests_carry_the_frame",
                "pass": all(
                    item.get("request", {}).get("image_sha256_matches_frame") is True
                    for item in rounds
                ),
            },
            {
                "name": "all_executed_rounds_arbitrated",
                "pass": all(
                    (item.get("arbitration") or {}).get("status")
                    == RouteArbitrationStatus.SELECTED
                    or (
                        (item.get("redecision") or {}).get("selected") is True
                        and (
                            (item.get("redecision") or {}).get("arbitration")
                            or {}
                        ).get("status")
                        == RouteArbitrationStatus.SELECTED
                    )
                    for item in rounds
                    if (item.get("execution") or {}).get("executed")
                ),
            },
            {
                "name": "execution_route_matches_effective_arbitration",
                "pass": all(
                    (
                        (item.get("execution") or {}).get("route_node_ids")
                        == (
                            item.get("arbitration_redecision")
                            or item.get("arbitration")
                            or {}
                        ).get("route_node_ids")
                    )
                    and (
                        (item.get("execution") or {}).get("model_selected_edge")
                        == (
                            item.get("arbitration_redecision")
                            or item.get("arbitration")
                            or {}
                        ).get("selected_edge")
                    )
                    and (item.get("execution") or {}).get("target_node_id")
                    in (
                        item.get("arbitration_redecision")
                        or item.get("arbitration")
                        or {}
                    ).get(
                        "route_node_ids", []
                    )
                    for item in rounds
                    if (item.get("execution") or {}).get("executed")
                ),
            },
            {
                "name": "at_least_one_successful_segment",
                "pass": successful_segments >= 1,
            },
            {
                "name": "kernel_host_executed_every_moving_segment",
                "pass": True
                if not kernel_exe
                else all(
                    (item.get("kernel") or {}).get("called") is True
                    and (
                        ((item.get("kernel") or {}).get("response") or {}).get(
                            "host_kind"
                        )
                        == "kernel"
                    )
                    and (
                        ((item.get("kernel") or {}).get("response") or {}).get(
                            "execution_status"
                        )
                        == "completed"
                    )
                    for item in rounds
                    if (item.get("execution") or {}).get("executed")
                ),
            },
            {
                "name": "kernel_bridge_authorized_every_execution",
                "pass": True
                if not kernel_exe
                else all(
                    (
                        (item.get("kernel") or {}).get("bridge_transaction") or {}
                    ).get("authorized")
                    is True
                    and (
                        (item.get("kernel") or {}).get("bridge_transaction") or {}
                    ).get("handler_finished")
                    is True
                    for item in rounds
                    if (item.get("execution") or {}).get("executed")
                ),
            },
            {
                "name": "kernel_motion_matches_post_state",
                "pass": True
                if not kernel_exe
                else all(
                    math.isclose(
                        float(item["execution"]["moved_m"]),
                        math.hypot(
                            item["execution"]["post_state"]["x"]
                            - item["execution"]["pre_state"]["x"],
                            item["execution"]["post_state"]["y"]
                            - item["execution"]["pre_state"]["y"],
                        ),
                        rel_tol=0.0,
                        abs_tol=1e-3,
                    )
                    for item in rounds
                    if (item.get("execution") or {}).get("executed")
                ),
            },
            {
                "name": "original_and_redecision_preserved",
                "pass": all(
                    item.get("decision") is not None
                    and (item.get("redecision") or {}).get("outcome") is not None
                    for item in rounds
                    if (item.get("redecision") or {}).get("attempted") is True
                ),
            },
            {
                "name": "redecision_used_original_frame_only_when_stationary",
                "pass": all(
                    (item.get("redecision") or {}).get("frame_id")
                    == item.get("observation", {}).get("frame", {}).get("frame_id")
                    and (
                        (item.get("redecision") or {}).get("same_frame") is not True
                        or (item.get("redecision") or {}).get("vehicle_stationary")
                        is True
                    )
                    for item in rounds
                    if (item.get("redecision") or {}).get("attempted") is True
                ),
            },
            {
                "name": "redecision_at_most_one_request",
                "pass": all(
                    ((item.get("redecision") or {}).get("request") or {}).get(
                        "request_count", 0
                    )
                    <= 1
                    for item in rounds
                    if (item.get("redecision") or {}).get("attempted") is True
                ),
            },
            {
                "name": "failed_redecision_did_not_execute",
                "pass": all(
                    (item.get("execution") or {}).get("executed") is not True
                    for item in rounds
                    if (item.get("redecision") or {}).get("attempted") is True
                    and (item.get("redecision") or {}).get("selected") is not True
                ),
            },
            {
                "name": "selected_redecision_matches_executed_route",
                "pass": all(
                    (item.get("redecision") or {})
                    .get("execution_linkage", {})
                    .get("execution_target_on_selected_route")
                    is True
                    for item in rounds
                    if (item.get("redecision") or {}).get("selected") is True
                ),
            },
            {
                "name": "recovery_used_new_frame",
                "pass": all(
                    item.get("observation_frame_id") is not None
                    and item.get("observation_frame_id") != item.get("failed_frame_id")
                    for item in result.get("recoveries", [])
                ),
            },
            {
                "name": "recovery_route_changed",
                "pass": all(
                    item.get("route_changed") is True
                    for item in result.get("recoveries", [])
                ),
            },
            {
                "name": "recovery_executed",
                "pass": all(
                    item.get("executed") is True
                    for item in result.get("recoveries", [])
                ),
            },
            {
                "name": "recovery_reached_goal",
                "pass": (
                    None
                    if not result.get("recoveries")
                    else result["recoveries"][-1].get("goal_reached") is True
                ),
            },
            {
                "name": "obstacle_injection_real_actor",
                "pass": (
                    None
                    if not getattr(args, "obstacle_round", 0)
                    else bool(result.get("obstacle_injection"))
                    and len(result.get("obstacles", [])) >= 1
                    and all(
                        item.get("spawned") is True and item.get("actor_id")
                        for item in result.get("obstacles", [])
                    )
                ),
            },
            {
                "name": "recovery_blocked_edges_recorded",
                "pass": (
                    None
                    if not getattr(args, "obstacle_round", 0)
                    else bool(result.get("recovery_blocked_edges"))
                ),
            },
            {
                "name": "recovery_selected_edge_unblocked",
                "pass": (
                    None
                    if not getattr(args, "obstacle_round", 0)
                    else _recovery_selected_edges_unblocked(result)
                ),
            },
            {
                "name": "mid_obstacle_real_actor_spawned",
                "pass": (
                    None
                    if not getattr(args, "mid_obstacle_round", 0)
                    else (
                        (result.get("mid_obstacle_trigger") or {}).get("spawned")
                        is True
                        and any(
                            item.get("phase") == "mid_segment"
                            and item.get("spawned") is True
                            and item.get("actor_id")
                            and item.get("injected_frame") is not None
                            for item in result.get("obstacles", [])
                        )
                    )
                ),
            },
            {
                "name": "mid_obstacle_was_ahead_of_the_moving_vehicle",
                "pass": (
                    None
                    if not getattr(args, "mid_obstacle_round", 0)
                    else all(
                        item.get("phase") == "mid_segment"
                        and item.get("vehicle_progress_m") is not None
                        and item.get("progress_m") is not None
                        and float(item["progress_m"])
                        > float(item["vehicle_progress_m"])
                        for item in result.get("obstacles", [])
                        if item.get("phase") == "mid_segment"
                    )
                    and any(
                        item.get("phase") == "mid_segment"
                        for item in result.get("obstacles", [])
                    )
                ),
            },
            {
                "name": "second_recovery_followed_real_motion",
                "pass": (
                    None
                    if not getattr(args, "mid_obstacle_round", 0)
                    else any(
                        item.get("trigger") == "post_motion_blocked_stop"
                        and item.get("failed_moved_m") is not None
                        and float(item["failed_moved_m"]) > 0.5
                        and item.get("node_id") is not None
                        and item.get("node_match_distance_m") is not None
                        and float(item["node_match_distance_m"])
                        <= MAX_NODE_DISTANCE_M
                        for item in result.get("recoveries", [])
                    )
                ),
            },
            {
                "name": "second_recovery_used_a_new_route",
                "pass": (
                    None
                    if not getattr(args, "mid_obstacle_round", 0)
                    else all(
                        item.get("route_changed") is True
                        and item.get("selected_edge")
                        and list(item.get("selected_edge"))
                        != list(item.get("failed_selected_edge") or ())
                        for item in result.get("recoveries", [])
                        if item.get("trigger") == "post_motion_blocked_stop"
                    )
                    and any(
                        item.get("trigger") == "post_motion_blocked_stop"
                        for item in result.get("recoveries", [])
                    )
                ),
            },
            {
                "name": "extra_obstacle_real_actor_spawned",
                "pass": (
                    None
                    if not getattr(args, "extra_obstacle_round", 0)
                    else (result.get("extra_obstacle") or {}).get("spawned")
                    is True
                    and (result.get("extra_obstacle") or {}).get("actor_id")
                    and (result.get("extra_obstacle") or {}).get(
                        "injected_frame"
                    )
                    is not None
                ),
            },
            {
                "name": "no_safe_route_refused_without_motion",
                "pass": (
                    None
                    if not getattr(args, "extra_obstacle_round", 0)
                    else (
                        any(
                            (
                                (item.get("arbitration") or {}).get("status")
                                == RouteArbitrationStatus.NO_COMPATIBLE_ROUTE
                            )
                            or item.get("status")
                            == RouteArbitrationStatus.NO_COMPATIBLE_ROUTE
                            for item in rounds
                            if item["round"]
                            >= int(args.extra_obstacle_round)
                        )
                        and all(
                            (item.get("execution") or {}).get("executed")
                            is not True
                            for item in rounds
                            if item["round"]
                            >= int(args.extra_obstacle_round)
                        )
                        and _collision_count() == 0
                    )
                ),
            },
            {
                "name": "stm_all_rounds_recorded",
                "pass": len(task_memory.records) == len(rounds)
                and [record.round_index for record in task_memory.records]
                == [item["round"] for item in rounds],
            },
            {
                "name": "stm_next_round_used_updated_history",
                "pass": all(
                    (item.get("observation") or {}).get("history_context_used")
                    is True
                    and (item.get("stm") or {}).get("records_before") == index - 1
                    for index, item in enumerate(rounds, start=1)
                    if index >= 2
                ),
            },
            {
                "name": "stm_history_contains_previous_round",
                "pass": all(
                    f'"round":{item["round"] - 1}'
                    in (item.get("stm") or {}).get("context_before", "")
                    for item in rounds
                    if item["round"] >= 2
                ),
            },
            {
                "name": "stm_history_context_present_in_prompt",
                "pass": all(
                    (item.get("observation") or {}).get(
                        "history_context_in_prompt"
                    )
                    is True
                    and (item.get("stm") or {}).get("context_before", "")
                    in (item.get("observation") or {}).get("prompt", "")
                    for item in rounds
                    if item["round"] >= 2
                ),
            },
            {
                "name": "stm_task_identity_stable",
                "pass": all(
                    record.task_id == task_memory.task_id
                    for record in task_memory.records
                ),
            },
            {
                "name": "stm_final_stop_reason_recorded",
                "pass": task_memory.stop_reason == task_status,
            },
            {
                "name": "all_executed_stops_confirmed",
                "pass": all(
                    (item.get("execution") or {}).get("stopped") is True
                    for item in rounds
                    if (item.get("execution") or {}).get("executed")
                ),
            },
            {
                "name": "goal_distance_within_tolerance",
                "pass": final_goal is not None
                and "distance_above_tolerance" not in final_goal.reasons,
            },
            {
                "name": "goal_heading_within_tolerance",
                "pass": final_goal is not None
                and "heading_outside_tolerance" not in final_goal.reasons,
            },
            {
                "name": "goal_stopped",
                "pass": final_goal is not None and final_goal.stopped,
            },
            {
                "name": "parking_verdict_confirmed",
                "pass": (
                    None if parking_verdict is None else parking_verdict.ok
                ),
            },
            {
                "name": "parking_no_collision",
                "pass": (
                    None
                    if SCENARIO != "carpark_parking"
                    else len(result.get("collision_events", [])) == 0
                ),
            },
            {
                "name": "parking_stable_stop",
                "pass": (
                    None if parking_stable is None else parking_stable["stable"]
                ),
            },
            {
                "name": "target_approach_verdict_confirmed",
                "pass": (
                    None
                    if not approach_only
                    else bool(
                        (result.get("target_approach_verdict") or {}).get("ok")
                    )
                ),
            },
            {
                "name": "target_approach_kernel_executed",
                "pass": (
                    None
                    if not approach_only
                    else bool(result.get("target_approach_kernel_executions"))
                ),
            },
            {
                "name": "settings_restored",
                "pass": None,  # filled in finally
            },
            {
                "name": "cleanup_no_leftovers",
                "pass": None,  # filled in finally
            },
        ]
        result["checks"] = checks
        acceptance_checks_ok = all(
            check["pass"] is True
            for check in checks
            if check["name"] not in ("settings_restored", "cleanup_no_leftovers")
            and check["pass"] is not None
        )
        if task_status == TaskStatus.EXECUTION_ERROR:
            result["status"] = "FAIL"
            exit_code = (
                EXIT_MODEL
                if (result.get("stop") or {}).get("reason") == MODEL_REQUEST_FAILED
                else EXIT_UNEXPECTED
            )
        elif task_status == TaskStatus.GOAL_REACHED and acceptance_checks_ok:
            result["status"] = "PASS"
            exit_code = EXIT_PASS
        elif task_status in (
            TaskStatus.DECISION_REJECTED,
            TaskStatus.SAFETY_STOPPED,
            TaskStatus.TIMEOUT,
            TaskStatus.MAX_ROUNDS,
            TaskStatus.GOAL_REACHED,
            TaskStatus.PARKING_NOT_CONFIRMED,
            TaskStatus.TARGET_APPROACH_NOT_CONFIRMED,
        ):
            result["status"] = "PARTIAL"
            exit_code = EXIT_PARTIAL
        else:
            result["status"] = "FAIL"
            exit_code = EXIT_PARTIAL
    except Exception as exc:
        result["status"] = "FAIL"
        result["task_status"] = TaskStatus.EXECUTION_ERROR
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        exit_code = EXIT_SETUP
    finally:
        if restore_opener is not None:
            restore_opener()
        if (
            not keep_runtime
            and host_client is not None
            and host_session_id is not None
        ):
            host_session_meta = result["meta"].setdefault(
                "host_session", {"session_id": host_session_id}
            )
            try:
                get_response, get_output = _kernel_session_control(
                    host_client,
                    "session.get",
                    {"session_id": host_session_id},
                    f"{run_id}-session-final-get",
                )
                host_session_meta["final_get"] = {
                    "accepted": get_response.accepted,
                    "session_state": get_response.session_state,
                    "context_revision": get_response.context_revision,
                    "turn": get_response.turn,
                    "error": (
                        None
                        if get_response.error is None
                        else dict(get_response.error)
                    ),
                    "context": (
                        None if get_output is None else get_output.get("context")
                    ),
                    "workflows": (
                        None if get_output is None else get_output.get("workflows")
                    ),
                    "task_count": (
                        None if get_output is None else get_output.get("task_count")
                    ),
                }
                close_response, close_output = _kernel_session_control(
                    host_client,
                    "session.close",
                    {"session_id": host_session_id},
                    f"{run_id}-session-close",
                )
                host_session_meta["close"] = {
                    "accepted": close_response.accepted,
                    "session_state": close_response.session_state,
                    "context_revision": close_response.context_revision,
                    "error": (
                        None
                        if close_response.error is None
                        else dict(close_response.error)
                    ),
                    "output": close_output,
                }
                after_close_response, after_close_output = _kernel_session_control(
                    host_client,
                    "session.get",
                    {"session_id": host_session_id},
                    f"{run_id}-session-get-after-close",
                )
                host_session_meta["get_after_close"] = {
                    "accepted": after_close_response.accepted,
                    "session_id": after_close_response.session_id,
                    "error": (
                        None
                        if after_close_response.error is None
                        else dict(after_close_response.error)
                    ),
                    "output": after_close_output,
                }
            except Exception as exc:
                host_session_meta["finalize_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
        if host_client is not None and not keep_runtime:
            try:
                host_client.close()
            except Exception as exc:
                result.setdefault("kernel_cleanup", {})["host_close_error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
            result.setdefault("kernel_cleanup", {})[
                "host_stderr_tail"
            ] = host_client.stderr_lines[-40:]
        if bridge is not None:
            transactions = bridge.transactions
            result["kernel_bridge_transactions"] = transactions
            if not keep_runtime:
                bridge.close()
            with open(out_dir / "kernel_bridge_transactions.jsonl", "w", encoding="utf-8") as handle:
                for transaction in transactions:
                    handle.write(json.dumps(transaction, ensure_ascii=False) + "\n")
        if active_round_video is not None:
            try:
                result["video_last"] = active_round_video.close()
            except Exception as exc:
                result.setdefault("video_cleanup", {})["error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
            active_round_video = None
        if session is not None and not keep_runtime:
            cleanup = cleanup_session(session.world, session.actors, session.original)
            session.actors = []
            result["cleanup"] = {
                "destroy_errors": cleanup["destroy_errors"],
                "leftover_vln_actors": cleanup["leftover_vln_actors"],
            }
            result["settings"] = {
                "before": session.original,
                "after": cleanup["settings_after"],
                "restored": cleanup["settings_restored"],
            }
            if "checks" in result:
                for check in result["checks"]:
                    if check["name"] == "settings_restored":
                        check["pass"] = cleanup["settings_restored"]
                    elif check["name"] == "cleanup_no_leftovers":
                        check["pass"] = cleanup["leftover_vln_actors"] == 0
                if result["status"] == "PASS" and not all(
                    check["pass"] is True
                    for check in result["checks"]
                    if check["pass"] is not None
                ):
                    result["status"] = "PARTIAL"
                    exit_code = EXIT_PARTIAL
        path = out_dir / "result.json"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False)
        print("wrote", path)
        summary = result.get("summary", {})
        print(
            "status=%s task_status=%s rounds=%s real_model_rounds=%s "
            "segments=%s goal_distance_m=%s"
            % (
                result.get("status"),
                result.get("task_status"),
                summary.get("attempted_rounds"),
                summary.get("real_model_rounds"),
                summary.get("successful_segments"),
                summary.get("final_goal_distance_m"),
            )
        )
    return exit_code, result


def main(argv: list[str] | None = None, runtime: dict | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario",
        choices=(
            "carpark",
            "carpark_parking",
            "town10_fork",
            "town10_multipoint",
            "town10_recovery",
            "town10_recovery_east",
            "town10_recovery_upstream",
            "town10_continuation",
        ),
        default="carpark",
        help="map/graph/floor profile; town10_fork uses Town10HD_Opt J719",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument(
        "--task-label",
        default=TASK_LABEL,
        help="evidence task label stored in result.json and the STM task id",
    )
    parser.add_argument(
        "--run-prefix",
        default=None,
        help="run id prefix; defaults to carla-06",
    )
    parser.add_argument(
        "--video-dir",
        default=None,
        help="optional directory for per-execution real onboard frames",
    )
    parser.add_argument(
        "--final-photo-dir",
        default=None,
        help="optional directory for one static post-run parking photo",
    )
    parser.add_argument(
        "--start-node",
        default=None,
        help="validated graph node where the ego is spawned",
    )
    parser.add_argument(
        "--start-previous-node",
        default=None,
        help=(
            "optional graph neighbour used to derive the spawn heading; "
            "required only when the start node has multiple incoming neighbours"
        ),
    )
    parser.add_argument(
        "--start-yaw-deg",
        type=float,
        default=None,
        help=(
            "optional explicit spawn yaw in degrees; the derived approach "
            "heading is used when omitted and both are recorded"
        ),
    )
    parser.add_argument(
        "--goal-node",
        default=None,
        help="validated graph node judged by the existing evaluate_goal",
    )
    parser.add_argument(
        "--target-binding-json",
        default=None,
        help=(
            "binding artifact produced by the target-binding step; the run is "
            "refused unless its status is 'bound', and its slot node becomes "
            "the parking goal"
        ),
    )
    parser.add_argument(
        "--parking-instruction",
        default=None,
        help=(
            "natural-language parking instruction; when supplied it must match "
            "the binding artifact instruction"
        ),
    )
    parser.add_argument(
        "--binding-dry-run",
        action="store_true",
        help=(
            "validate the binding artifact and the bound route, print the "
            "resolved goal, and exit without spawning or contacting the Host"
        ),
    )
    parser.add_argument(
        "--target-approach-only",
        action="store_true",
        help=(
            "stop at the bound bay's safe approach node (park_entry/bay11_turn) "
            "instead of executing the parking arc; requires a bound artifact"
        ),
    )
    parser.add_argument(
        "--task-id",
        default=None,
        help="task identity recorded with the run; defaults to --task-label",
    )
    parser.add_argument(
        "--target-id",
        default=None,
        help="target identity recorded with the run; must equal the bound bay_id",
    )
    parser.add_argument(
        "--spawn-x",
        type=float,
        default=None,
        help=(
            "optional explicit spawn x near --start-node; use with --spawn-y "
            "when the exact waypoint transform collides with static geometry. "
            "The distance to the start node is limited to 2.0 m."
        ),
    )
    parser.add_argument(
        "--spawn-y",
        type=float,
        default=None,
        help="optional explicit spawn y; must be supplied with --spawn-x",
    )
    parser.add_argument(
        "--spawn-z",
        type=float,
        default=None,
        help=(
            "spawn height; carpark defaults to 6.7 m, town10_fork to 0.5 m"
        ),
    )
    parser.add_argument(
        "--route-name",
        default=None,
        help="evidence label; defaults to '<start>-to-<goal>'",
    )
    parser.add_argument(
        "--targets",
        default="B1",
        help=(
            "comma-separated visible target per round; the last one is reused "
            "if there are more rounds. The same B1 sign is visible from the "
            "w4/w6/w8 decision points under the per-round lenses."
        ),
    )
    parser.add_argument(
        "--round-fovs",
        default="100,70",
        help=(
            "comma-separated real camera FOV per round; the last value is "
            "reused. The later decision points need the narrower lens for the "
            "B1 sign to be legible to the model."
        ),
    )
    parser.add_argument("--target-kind", default="区域标识")
    parser.add_argument(
        "--target-note",
        default=(
            "若画面中出现多个 {target} 标识，请以距离车辆最近、最清晰的一个为准，"
            "并据此判断相对方位。"
        ),
        help=(
            "caller-supplied disambiguation note inserted by the existing "
            "TARGET_DIRECTION prompt; it describes which instance to use and "
            "never states the direction"
        ),
    )
    parser.add_argument(
        "--instruction",
        default=(
            "观察当前地下停车场环境，判断下一步适合沿当前通道直行、向左转还是向右转；"
            "若图像证据不足或无法确定安全方向，应明确表示不确定，不要猜测。"
        ),
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=8,
        help="maximum navigation rounds; the task stops earlier on goal/failure",
    )
    parser.add_argument(
        "--max-total-wall-seconds",
        type=float,
        default=900.0,
        help="wall-clock limit for the whole task, including model calls",
    )
    parser.add_argument(
        "--goal-distance-tolerance",
        type=float,
        default=GOAL_DISTANCE_TOLERANCE_M,
        help="allowed distance from the goal node in metres",
    )
    parser.add_argument(
        "--goal-heading-tolerance-deg",
        type=float,
        default=GOAL_HEADING_TOLERANCE_DEG,
        help="allowed heading error from the w9->goal approach bearing",
    )
    parser.add_argument(
        "--goal-stop-speed",
        type=float,
        default=GOAL_STOP_SPEED_MPS,
        help="maximum real speed accepted as stopped at the goal",
    )
    parser.add_argument(
        "--segment-nodes",
        type=int,
        default=2,
        help=(
            "nodes to advance along the selected A* route before re-observing; "
            "must be at least 1 (the first node is the model-selected edge)"
        ),
    )
    parser.add_argument("--max-segment-sim-seconds", type=float, default=30.0)
    parser.add_argument(
        "--parking-speed-cap",
        type=float,
        default=0.35,
        help="low-speed cap for the final bay arc (m/s)",
    )
    parser.add_argument(
        "--max-parking-sim-seconds",
        type=float,
        default=90.0,
        help=(
            "requested parking simulation-time budget; the controller raises "
            "it for long routes (hard cap 240 s), never lowers the existing "
            "stall/off-route/safety exits"
        ),
    )
    parser.add_argument(
        "--max-parking-steps",
        type=int,
        default=1400,
        help=(
            "requested parking step budget; the controller raises it from the "
            "selected route length and speed cap (hard cap 4000), never lowers "
            "the existing stall/off-route/safety exits"
        ),
    )
    parser.add_argument(
        "--video-width", type=int, default=640, help="onboard video width"
    )
    parser.add_argument(
        "--video-height", type=int, default=360, help="onboard video height"
    )
    parser.add_argument(
        "--video-fps", type=float, default=10.0, help="onboard video frame rate"
    )
    parser.add_argument("--max-steps", type=int, default=800)
    parser.add_argument("--max-new-tokens", type=int, default=1800)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument(
        "--enable-thinking",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "request-level thinking toggle for both the normal round and the "
            "one-shot route redecision; defaults to True (production)"
        ),
    )
    parser.add_argument(
        "--kernel-host",
        default=None,
        help=(
            "path to the compiled Agent-Kernel kernel_host, or 'env' to use "
            "VLN_KERNEL_HOST_EXE. When supplied, every arbitrated segment is "
            "executed through the real Kernel Runtime and the parking.move "
            "capability instead of being driven directly."
        ),
    )
    parser.add_argument(
        "--kernel-exec-timeout-ms",
        type=int,
        default=180000,
        help="Kernel host timeout for one CARLA capability execution (ms)",
    )
    parser.add_argument(
        "--host-planner",
        action="store_true",
        help=(
            "route every model call through the compiled Host's real Kernel "
            "Planner path (capability planner.plan -> TaichuPlanningEngine -> "
            "loopback planner bridge). Requires --kernel-host and the "
            "VLN_TAICHU_PLANNER_BRIDGE / VLN_TAICHU_PLANNER_TOKEN environment "
            "used by the Host"
        ),
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help=(
            "persistent Kernel Session id shared by planner.plan and "
            "parking.move; defaults to the run id when --host-planner is used"
        ),
    )
    parser.add_argument(
        "--safety-probe-distance",
        type=float,
        default=7.0,
        help=(
            "minimum forward precheck distance in metres; the default 7.0 m "
            "preserves the 04A-02/04B/04C behavior, while 04D may use a longer "
            "conservative lookahead to detect a blocker after branch divergence"
        ),
    )
    parser.add_argument(
        "--obstacle-round",
        type=int,
        default=0,
        help=(
            "inject the configured real static obstacle after this round's "
            "model/arbitration decision and before its execution; 0 disables"
        ),
    )
    parser.add_argument(
        "--obstacle-blueprint",
        default="static.prop.trafficcone01",
        help="CARLA static prop used as the real route obstruction",
    )
    parser.add_argument("--obstacle-x", type=float, default=-4.0)
    parser.add_argument("--obstacle-y", type=float, default=-15.6)
    parser.add_argument("--obstacle-z", type=float, default=5.9)
    parser.add_argument("--obstacle-yaw", type=float, default=0.0)
    parser.add_argument("--obstacle2-x", type=float, default=None)
    parser.add_argument("--obstacle2-y", type=float, default=None)
    parser.add_argument(
        "--remove-obstacles-round",
        type=int,
        default=0,
        help=(
            "destroy every injected real obstacle at the start of this round; "
            "0 disables. Used to test re-evaluation after a controlled real "
            "state change"
        ),
    )
    parser.add_argument(
        "--mid-obstacle-round",
        type=int,
        default=0,
        help=(
            "spawn the second real static obstacle from inside this round's "
            "Kernel-invoked driving segment, after the vehicle has reached the "
            "configured edge; 0 disables"
        ),
    )
    parser.add_argument(
        "--mid-obstacle-edge",
        default="bypass_r1,bypass_r2",
        help="FROM,TO graph edge the moving segment must be on when it appears",
    )
    parser.add_argument(
        "--mid-obstacle-edge-s",
        type=float,
        default=3.8,
        help="distance along that edge of the real obstacle (m)",
    )
    parser.add_argument(
        "--mid-obstacle-trigger-edge-s",
        type=float,
        default=0.1,
        help="arm the real obstacle once the vehicle passes this edge distance",
    )
    parser.add_argument(
        "--mid-obstacle-blueprint",
        default="static.prop.trafficcone01",
        help="CARLA static prop used as the second real obstruction",
    )
    parser.add_argument(
        "--mid-obstacle-z",
        type=float,
        default=5.8,
        help="spawn height of the second obstruction (m)",
    )
    parser.add_argument(
        "--mid-obstacle-yaw-offset-deg",
        type=float,
        default=90.0,
        help=(
            "yaw added to the local path tangent; 90 makes a long prop span "
            "across the lane"
        ),
    )
    parser.add_argument(
        "--extra-obstacle-round",
        type=int,
        default=0,
        help=(
            "spawn an extra real obstruction before this round's observation; "
            "used for the no-safe-route refusal case; 0 disables"
        ),
    )
    parser.add_argument(
        "--extra-obstacle-blueprint",
        default="static.prop.trafficcone01",
    )
    parser.add_argument("--extra-obstacle-x", type=float, default=0.0)
    parser.add_argument("--extra-obstacle-y", type=float, default=-13.0)
    parser.add_argument("--extra-obstacle-z", type=float, default=5.9)
    parser.add_argument("--extra-obstacle-yaw", type=float, default=0.0)
    parser.add_argument(
        "--recover-after-safety-stop",
        action="store_true",
        help=(
            "when a safety precheck refuses a segment without moving the "
            "vehicle, capture a new frame and let the next round choose a "
            "different legal edge; bounded by --max-recovery-attempts"
        ),
    )
    parser.add_argument(
        "--max-recovery-attempts",
        type=int,
        default=1,
        help="maximum cross-round recovery attempts after a safety stop",
    )
    parser.add_argument(
        "--max-visual-recovery-attempts",
        type=int,
        default=3,
        help=(
            "maximum bounded re-observations after a visual verification "
            "failure in one task"
        ),
    )
    parser.add_argument(
        "--max-visual-recovery-per-type",
        type=int,
        default=2,
        help="maximum re-observations for one visual uncertainty type",
    )
    parser.add_argument(
        "--no-visual-recovery",
        action="store_true",
        help=(
            "disable bounded re-observation after a visual verification "
            "failure; the failed decision is recorded without a new frame"
        ),
    )
    parser.add_argument(
        "--no-route-redecision",
        action="store_true",
        help=(
            "disable the one-shot re-decision after no_compatible_route; the "
            "original decision and safe stop are recorded without a second "
            "model request"
        ),
    )
    args = parser.parse_args(argv)
    configure_scenario(args.scenario)
    explicit_goal_node = args.goal_node
    binding_artifact = None
    args.task_id = args.task_id or args.task_label
    if args.target_binding_json:
        if args.scenario != "carpark_parking":
            parser.error(
                "--target-binding-json requires --scenario carpark_parking: the "
                "bound slot nodes belong to the parking graph"
            )
        try:
            binding_artifact = load_binding_artifact(args.target_binding_json)
            bound_goal = resolve_bound_goal(
                binding_artifact,
                instruction=args.parking_instruction,
            )
        except BindingRuntimeError as error:
            parser.error(str(error))
        args.target_binding_artifact = binding_artifact
        args.target_binding_meta = binding_artifact.to_metadata()
        args.target_id = args.target_id or binding_artifact.bay_id
        if args.target_id != binding_artifact.bay_id:
            parser.error(
                f"--target-id {args.target_id!r} does not match the bound bay "
                f"{binding_artifact.bay_id!r}"
            )
        if args.target_approach_only:
            try:
                approach_node = approach_node_for_slot(
                    binding_artifact.slot_node_id
                )
            except (KeyError, ValueError) as error:
                parser.error(str(error))
            if not GRAPH.has_node(approach_node):
                parser.error(
                    f"bound approach node {approach_node!r} is not in the "
                    f"{args.scenario} graph"
                )
            if explicit_goal_node is not None and explicit_goal_node != approach_node:
                parser.error(
                    f"--goal-node {explicit_goal_node!r} conflicts with the "
                    f"bound approach node {approach_node!r}"
                )
            args.goal_node = approach_node
            args.target_approach_meta = {
                "enabled": True,
                "task_id": args.task_id,
                "target_id": args.target_id,
                "bay_id": binding_artifact.bay_id,
                "slot_node_id": binding_artifact.slot_node_id,
                "approach_node_id": approach_node,
            }
        else:
            if explicit_goal_node is not None and explicit_goal_node != bound_goal:
                parser.error(
                    f"--goal-node {explicit_goal_node!r} conflicts with the "
                    f"bound target {bound_goal!r}"
                )
            args.goal_node = bound_goal
            args.target_approach_meta = None
    elif args.binding_dry_run:
        parser.error("--binding-dry-run requires --target-binding-json")
    elif args.target_approach_only:
        parser.error("--target-approach-only requires --target-binding-json")
    elif args.parking_instruction:
        parser.error("--parking-instruction requires --target-binding-json")
    elif args.target_id:
        parser.error("--target-id requires --target-binding-json")
    if args.start_node is None:
        args.start_node = DEFAULT_START_NODE
    if args.goal_node is None:
        args.goal_node = DEFAULT_GOAL_NODE
    if args.spawn_z is None:
        args.spawn_z = 6.7 if SCENARIO in ("carpark", "carpark_parking") else 0.5
    if args.kernel_exec_timeout_ms < 1:
        parser.error("--kernel-exec-timeout-ms must be positive")
    if args.rounds < 1:
        parser.error("--rounds must be at least 1")
    if args.max_recovery_attempts < 0:
        parser.error("--max-recovery-attempts must be non-negative")
    if args.max_visual_recovery_attempts < 0:
        parser.error("--max-visual-recovery-attempts must be non-negative")
    if args.max_visual_recovery_per_type < 0:
        parser.error("--max-visual-recovery-per-type must be non-negative")
    if args.obstacle_round < 0:
        parser.error("--obstacle-round must be non-negative")
    if args.mid_obstacle_round < 0:
        parser.error("--mid-obstacle-round must be non-negative")
    mid_edge = tuple(
        part.strip() for part in str(args.mid_obstacle_edge).split(",")
    )
    if len(mid_edge) != 2 or not all(mid_edge):
        parser.error("--mid-obstacle-edge must be FROM,TO")
    for node_id in mid_edge:
        if not GRAPH.has_node(node_id):
            parser.error(f"unknown --mid-obstacle-edge node {node_id!r}")
    if mid_edge[0] == mid_edge[1]:
        parser.error("--mid-obstacle-edge endpoints must differ")
    args.mid_obstacle_edge = mid_edge
    for name in ("mid_obstacle_edge_s", "mid_obstacle_trigger_edge_s"):
        value = getattr(args, name)
        if not math.isfinite(value) or value < 0:
            parser.error(f"--{name.replace('_', '-')} must be non-negative")
    if args.mid_obstacle_trigger_edge_s >= args.mid_obstacle_edge_s:
        parser.error(
            "--mid-obstacle-trigger-edge-s must be below --mid-obstacle-edge-s"
        )
    if not math.isfinite(args.mid_obstacle_z) or not 4.0 <= args.mid_obstacle_z <= 8.0:
        parser.error("--mid-obstacle-z must be finite and in [4.0, 8.0]")
    if not math.isfinite(args.mid_obstacle_yaw_offset_deg):
        parser.error("--mid-obstacle-yaw-offset-deg must be finite")
    if args.extra_obstacle_round < 0:
        parser.error("--extra-obstacle-round must be non-negative")
    if not (
        math.isfinite(args.extra_obstacle_x)
        and math.isfinite(args.extra_obstacle_y)
        and math.isfinite(args.extra_obstacle_z)
        and math.isfinite(args.extra_obstacle_yaw)
    ):
        parser.error("--extra-obstacle x/y/z/yaw must be finite")
    if args.mid_obstacle_round and not args.recover_after_safety_stop:
        parser.error(
            "--mid-obstacle-round requires --recover-after-safety-stop so the "
            "second interruption can be re-observed"
        )
    if not math.isfinite(args.safety_probe_distance) or not (
        7.0 <= args.safety_probe_distance <= 30.0
    ):
        parser.error("--safety-probe-distance must be in [7.0, 30.0]")
    if args.segment_nodes < 1:
        parser.error("--segment-nodes must be at least 1")
    if args.max_total_wall_seconds <= 0:
        parser.error("--max-total-wall-seconds must be positive")
    if args.goal_distance_tolerance <= 0:
        parser.error("--goal-distance-tolerance must be positive")
    if args.goal_heading_tolerance_deg < 0 or args.goal_heading_tolerance_deg > 180:
        parser.error("--goal-heading-tolerance-deg must be in [0, 180]")
    if args.goal_stop_speed < 0:
        parser.error("--goal-stop-speed must be non-negative")
    if not GRAPH.has_node(args.start_node):
        parser.error(f"unknown --start-node {args.start_node!r}")
    if not GRAPH.has_node(args.goal_node):
        parser.error(f"unknown --goal-node {args.goal_node!r}")
    if args.start_node == args.goal_node:
        parser.error("--start-node and --goal-node must differ")
    if args.start_previous_node is not None and not GRAPH.has_node(
        args.start_previous_node
    ):
        parser.error(
            f"unknown --start-previous-node {args.start_previous_node!r}"
        )
    if args.start_yaw_deg is not None and not math.isfinite(args.start_yaw_deg):
        parser.error("--start-yaw-deg must be finite")
    if (args.spawn_x is None) != (args.spawn_y is None):
        parser.error("--spawn-x and --spawn-y must be supplied together")
    if not math.isfinite(args.spawn_z) or not SPAWN_Z_MIN <= args.spawn_z <= SPAWN_Z_MAX:
        parser.error(
            f"--spawn-z must be finite and in [{SPAWN_Z_MIN}, {SPAWN_Z_MAX}]"
        )
    if args.spawn_x is not None:
        if not (math.isfinite(args.spawn_x) and math.isfinite(args.spawn_y)):
            parser.error("--spawn-x/--spawn-y must be finite")
        node_x, node_y = NODES[args.start_node]
        if math.hypot(args.spawn_x - node_x, args.spawn_y - node_y) > MAX_NODE_DISTANCE_M:
            parser.error(
                "--spawn-x/--spawn-y must be within "
                f"{MAX_NODE_DISTANCE_M:.1f} m of --start-node"
            )
    route_path, route_status = GRAPH.astar(args.start_node, args.goal_node)
    if route_path is None:
        parser.error(
            f"no route {args.start_node!r}->{args.goal_node!r} "
            f"(A* status {route_status!r})"
        )
    if args.binding_dry_run:
        print(
            json.dumps(
                {
                    "status": "binding_accepted",
                    "executed": False,
                    "scenario": args.scenario,
                    "task_id": args.task_id,
                    "target_id": args.target_id,
                    "start_node": args.start_node,
                    "goal_node": args.goal_node,
                    "planned_route": list(route_path),
                    "route_status": route_status,
                    "target_binding": args.target_binding_meta,
                    "target_approach": getattr(args, "target_approach_meta", None),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    exit_code, _ = run(args, runtime=runtime)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
