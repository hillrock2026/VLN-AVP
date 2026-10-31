#!/usr/bin/env python3
"""M1-VLN-CARLA-01B: minimal continuous path planning and tracking in the
UndergroundCarPark map.

The map has no CARLA OpenDrive topology (get_topology() is empty), so this
script defines a small hand-verified waypoint graph, plans with A*, and follows
the result with a Pure Pursuit controller. Safety stopping uses forward rays
along the planned corridor plus vertical floor probes, not the collision
sensor alone.

Examples:
    python scripts/carla_parking_nav.py --check-paths
    python scripts/carla_parking_nav.py --scenario nominal --screenshots
    python scripts/carla_parking_nav.py --scenario obstacle
    python scripts/carla_parking_nav.py --scenario timeout --max-sim-seconds 4
"""

import argparse
import json
import math
import os
import struct
import sys
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import carla  # noqa: E402  (CARLA client is only available in the CARLA venv)

from vln.carla.route_control import (  # noqa: E402
    SegmentMonitor,
    cumulative_lengths,
    forward_safety_verdict,
    forward_stop_threshold,
    point_at_s,
    project_to_path,
    pure_pursuit_command,
)
from vln.carla.parking_geometry import Footprint  # noqa: E402
from vln.carla.waypoints import (  # noqa: E402
    UNDERGROUND_CARPARK_EDGES,
    UNDERGROUND_CARPARK_GOAL_NODE,
    UNDERGROUND_CARPARK_START_NODE,
    underground_carpark_graph,
)

MAP_NAME = "UndergroundCarPark"
VEHICLE_BP = "vehicle.dodge.charger"
FIXED_DT = 0.05
EGO_ROLE = "vln_ego"
OBSTACLE_ROLE = "vln_obstacle"
CAM_ROLE = "vln_cam"
ROLE_PREFIX = "vln_"

GRAPH = underground_carpark_graph()
NODES = {name: (node.x, node.y) for name, node in GRAPH.nodes.items()}
EDGES = [tuple(edge) for edge in UNDERGROUND_CARPARK_EDGES]
START_NODE = UNDERGROUND_CARPARK_START_NODE
GOAL_NODE = UNDERGROUND_CARPARK_GOAL_NODE

# Dodge Charger bounding box from CARLA: extent.x = 2.503 m. The front safety
# rays start just outside the front bumper.
FRONT_MARGIN = 0.30
# The effective steering limit and wheelbase live with the shared Pure Pursuit
# implementation in vln.carla.route_control.



def log(*args):
    print(*args, flush=True)


def _loc_dict(location):
    return {
        "x": round(float(location.x), 3),
        "y": round(float(location.y), 3),
        "z": round(float(location.z), 3),
    }


def _raw_hit_dict(hit):
    return {
        "location": _loc_dict(hit.location),
        "label": str(getattr(hit, "label", None)),
        "actor_type": getattr(getattr(hit, "actor", None), "type_id", None),
    }


def _cast_for_safety(session, start, end, with_details):
    """Return (hit_location, hit_metadata).

    ``hit_metadata`` is only populated when the caller asked for diagnostics.
    The normal safety path keeps using ``session.ray`` so the existing
    behaviour and cost are unchanged.
    """

    if with_details and hasattr(session, "ray_hit"):
        raw = session.ray_hit(start, end)
        if raw is None:
            return None, None
        return raw.location, _raw_hit_dict(raw)
    hit = session.ray(start, end)
    if hit is None:
        return None, None
    return hit, {"location": _loc_dict(hit)}


def astar(start, goal):
    """Return (path, status) from the shared graph's deterministic A*."""

    return GRAPH.astar(start, goal)


def path_points(path):
    return [NODES[name] for name in path]


def write_png(path, width, height, rgb):
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw.extend(rgb[y * stride:(y + 1) * stride])

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)


def draw_disc(buf, width, height, cx, cy, radius, color):
    r2 = radius * radius
    for y in range(max(0, int(cy - radius)), min(height, int(cy + radius) + 1)):
        for x in range(max(0, int(cx - radius)), min(width, int(cx + radius) + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r2:
                i = (y * width + x) * 3
                buf[i:i + 3] = bytes(color)


def draw_line(buf, width, height, x1, y1, x2, y2, color, thickness=1):
    steps = max(1, int(max(abs(x2 - x1), abs(y2 - y1))))
    for i in range(steps + 1):
        t = i / steps
        x = int(round(x1 + (x2 - x1) * t))
        y = int(round(y1 + (y2 - y1) * t))
        draw_disc(buf, width, height, x, y, max(1, thickness // 2), color)


def plot_trajectory(points, cum, records, out_path):
    xs = [p[0] for p in points] + [r["x"] for r in records]
    ys = [p[1] for p in points] + [r["y"] for r in records]
    x_min, x_max = min(xs) - 2.0, max(xs) + 2.0
    y_min, y_max = min(ys) - 2.0, max(ys) + 2.0
    width, height = 900, 900
    margin = 50
    scale = min((width - 2 * margin) / max(1e-6, x_max - x_min),
                (height - 2 * margin) / max(1e-6, y_max - y_min))
    buf = bytearray([242, 242, 242] * width * height)

    def to_px(x, y):
        return (margin + (x - x_min) * scale,
                height - margin - (y - y_min) * scale)

    # grid every 5 m
    gx = math.ceil(x_min / 5.0) * 5.0
    while gx <= x_max:
        x1, y1 = to_px(gx, y_min)
        x2, y2 = to_px(gx, y_max)
        draw_line(buf, width, height, x1, y1, x2, y2, (218, 218, 218), 1)
        gx += 5.0
    gy = math.ceil(y_min / 5.0) * 5.0
    while gy <= y_max:
        x1, y1 = to_px(x_min, gy)
        x2, y2 = to_px(x_max, gy)
        draw_line(buf, width, height, x1, y1, x2, y2, (218, 218, 218), 1)
        gy += 5.0

    # planned route and waypoints
    for i in range(len(points) - 1):
        x1, y1 = to_px(*points[i])
        x2, y2 = to_px(*points[i + 1])
        draw_line(buf, width, height, x1, y1, x2, y2, (40, 95, 200), 4)
    for p in points:
        x, y = to_px(*p)
        draw_disc(buf, width, height, x, y, 5, (40, 95, 200))

    # actual trajectory
    for i in range(len(records) - 1):
        x1, y1 = to_px(records[i]["x"], records[i]["y"])
        x2, y2 = to_px(records[i + 1]["x"], records[i + 1]["y"])
        draw_line(buf, width, height, x1, y1, x2, y2, (20, 155, 65), 3)

    # start / goal / final pose
    sx, sy = to_px(*points[0])
    gx, gy = to_px(*points[-1])
    draw_disc(buf, width, height, sx, sy, 11, (0, 160, 0))
    draw_disc(buf, width, height, gx, gy, 11, (220, 40, 40))
    if records:
        fx, fy = to_px(records[-1]["x"], records[-1]["y"])
        draw_disc(buf, width, height, fx, fy, 8, (20, 20, 20))

    write_png(out_path, width, height, buf)
    return out_path


class LatestImage:
    """Keep only the newest frame, so a long run does not accumulate images."""

    def __init__(self):
        self.image = None

    def __call__(self, image):
        self.image = image


class Session:
    def __init__(self, host, port, out_dir, map_name=MAP_NAME):
        self.client = carla.Client(host, port)
        self.client.set_timeout(120.0)
        self.world = self.client.get_world()
        if not self.world.get_map().name.endswith(map_name):
            self.client.load_world(map_name)
            self.world = self.client.get_world()
        settings = self.world.get_settings()
        self.original = {
            "synchronous_mode": settings.synchronous_mode,
            "no_rendering_mode": settings.no_rendering_mode,
            "fixed_delta_seconds": settings.fixed_delta_seconds,
            "substepping": settings.substepping,
            "max_substeps": settings.max_substeps,
            "max_substep_delta_time": settings.max_substep_delta_time,
        }
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = FIXED_DT
        settings.no_rendering_mode = False
        self.world.apply_settings(settings)
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        self.actors = []
        self.cam_bp = self.world.get_blueprint_library().find("sensor.camera.rgb")
        self.cam_bp.set_attribute("image_size_x", "1280")
        self.cam_bp.set_attribute("image_size_y", "720")
        self.cam_bp.set_attribute("fov", "90")

    def close(self):
        self.destroy_actors()
        restored = self.world.get_settings()
        for key, value in self.original.items():
            setattr(restored, key, value)
        self.world.apply_settings(restored)

    def tick(self, n=1):
        for _ in range(n):
            self.world.tick()

    def sim_time(self):
        return self.world.get_snapshot().timestamp.elapsed_seconds

    def spawn_vehicle(self, role, x, y, z, yaw):
        bp = self.world.get_blueprint_library().find(VEHICLE_BP)
        bp.set_attribute("role_name", role)
        vehicle = self.world.try_spawn_actor(
            bp, carla.Transform(carla.Location(x=x, y=y, z=z), carla.Rotation(yaw=yaw)))
        if vehicle is None:
            raise RuntimeError("spawn failed for %s at (%.2f, %.2f)" % (role, x, y))
        self.actors.append(vehicle)
        return vehicle

    def destroy_actors(self):
        for actor in reversed(self.actors):
            try:
                if actor.is_alive:
                    actor.destroy()
            except RuntimeError:
                pass
        self.actors = []

    def destroy_leftovers(self):
        leftovers = [a for a in self.world.get_actors()
                     if a.attributes.get("role_name", "").startswith(ROLE_PREFIX)]
        for actor in leftovers:
            try:
                actor.destroy()
            except RuntimeError:
                pass
        return leftovers

    def leftover_count(self):
        return len([a for a in self.world.get_actors()
                    if a.attributes.get("role_name", "").startswith(ROLE_PREFIX)])

    def ray_hit(self, start, end):
        hits = self.world.cast_ray(start, end)
        return hits[0] if hits else None

    def ray(self, start, end):
        hit = self.ray_hit(start, end)
        return None if hit is None else hit.location

    def floor_at(self, x, y, z=7.0):
        hit = self.ray(carla.Location(x, y, z), carla.Location(x, y, z - 2.2))
        return None if hit is None else round(hit.z, 3)

    def spawn_chase_camera(self, vehicle):
        camera = self.world.spawn_actor(
            self.cam_bp,
            carla.Transform(carla.Location(x=-5.5, y=0, z=2.4), carla.Rotation(pitch=-8)),
            attach_to=vehicle)
        self.actors.append(camera)
        latest = LatestImage()
        camera.listen(latest)
        return camera, latest

    def save_latest(self, latest, name):
        if latest.image is None:
            return None
        path = os.path.join(self.out_dir, name)
        latest.image.save_to_disk(path)
        log("  saved", path)
        return path

    def brake_to_stop(self, vehicle, max_ticks=80):
        vehicle.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0, steer=0.0))
        for _ in range(max_ticks):
            self.tick()
            v = vehicle.get_velocity()
            if math.hypot(v.x, v.y) < 0.2:
                break
        self.tick(5)


def state_of(vehicle, session):
    t = vehicle.get_transform()
    v = vehicle.get_velocity()
    return {
        "t": round(session.sim_time(), 3),
        "x": round(t.location.x, 3),
        "y": round(t.location.y, 3),
        "z": round(t.location.z, 3),
        "yaw": round(t.rotation.yaw, 3),
        "speed": round(math.hypot(v.x, v.y), 3),
    }


def validate_waypoints(
    session,
    path,
    nodes=None,
    expected_floor=5.80,
    floor_probe_z=7.0,
):
    report = {}
    ok = True
    source = NODES if nodes is None else nodes
    for name in path:
        x, y = source[name]
        floor = session.floor_at(x, y, z=floor_probe_z)
        good = floor is not None and abs(floor - expected_floor) < 0.10
        report[name] = {"x": x, "y": y, "floor_z": floor, "ok": good}
        ok = ok and good
    return ok, report


def safety_check(
    session,
    vehicle,
    points,
    cum,
    s,
    *,
    floor_probe_z=7.6,
    ray_z_offset=0.35,
    ray_z_offsets=None,
    lateral_offsets=None,
    path_origin_s=None,
    min_probe_distance_m=7.0,
    reverse=False,
    details_out=None,
    stop_distance_m=None,
):
    if details_out is not None and not isinstance(details_out, dict):
        raise TypeError("details_out must be a dict or None")
    if stop_distance_m is not None:
        if (
            type(stop_distance_m) not in (int, float)
            or not math.isfinite(float(stop_distance_m))
            or stop_distance_m <= 0
        ):
            raise ValueError("stop_distance_m must be a finite positive number or None")
    with_details = details_out is not None
    st = vehicle.get_transform()
    loc = st.location
    ego_yaw = math.radians(st.rotation.yaw)
    ego_footprint = Footprint(
        vehicle.bounding_box.extent.x,
        vehicle.bounding_box.extent.y,
        FRONT_MARGIN,
    )
    fwd = st.get_forward_vector()
    if reverse:
        fwd = carla.Vector3D(-fwd.x, -fwd.y, -fwd.z)
    probe_source = "rear" if reverse else "front"
    front = carla.Location(
        x=loc.x + fwd.x * (vehicle.bounding_box.extent.x + FRONT_MARGIN),
        y=loc.y + fwd.y * (vehicle.bounding_box.extent.x + FRONT_MARGIN),
        z=loc.z + ray_z_offset)
    v = math.hypot(vehicle.get_velocity().x, vehicle.get_velocity().y)
    stop_dist = (
        forward_stop_threshold(v)
        if stop_distance_m is None
        else float(stop_distance_m)
    )
    # Use the path tangent rather than the goal point: near the target the goal
    # can lie behind the front bumper, which would make the ray point backwards.
    p0 = point_at_s(points, cum, s)
    p1 = point_at_s(points, cum, min(cum[-1], s + 1.0))
    if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) < 1e-3:
        p0, p1 = points[-2], points[-1]
    seg_len = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    dir_x, dir_y = (p1[0] - p0[0]) / seg_len, (p1[1] - p0[1]) / seg_len
    lateral = (-dir_y, dir_x)
    if type(min_probe_distance_m) not in (int, float) or not math.isfinite(
        float(min_probe_distance_m)
    ) or min_probe_distance_m < 7.0:
        raise ValueError("min_probe_distance_m must be a finite number >= 7.0")
    if ray_z_offsets is None:
        heights = (float(ray_z_offset),)
    else:
        heights = tuple(float(value) for value in ray_z_offsets)
        if not heights or any(
            not math.isfinite(value) or value < 0.0 for value in heights
        ):
            raise ValueError("ray_z_offsets must be a non-empty set of heights >= 0")
    if lateral_offsets is None:
        offsets = (-0.6, 0.0, 0.6)
    else:
        offsets = tuple(float(value) for value in lateral_offsets)
        if not offsets or any(not math.isfinite(value) for value in offsets):
            raise ValueError("lateral_offsets must be a non-empty set of finite values")
    if path_origin_s is None:
        origins = ()
    else:
        origins = tuple(float(value) for value in path_origin_s)
        if not origins or any(
            not math.isfinite(value) or value < 0.0 or value > cum[-1]
            for value in origins
        ):
            raise ValueError("path_origin_s must be within the path")
    probe_dist = max(float(min_probe_distance_m), stop_dist + 2.0)
    min_hit = None
    rays = []
    ground_probes = []

    def _record_ray(source, height, offset, start, end, hit_loc, hit_meta, origin, origin_s=None):
        record = {
            "source": source,
            "height_m": round(height, 3),
            "lateral_offset_m": round(offset, 3),
            "start": _loc_dict(start),
            "end": _loc_dict(end),
        }
        if origin_s is not None:
            record["origin_s"] = round(origin_s, 3)
        if hit_loc is not None:
            meta = dict(hit_meta or {"location": _loc_dict(hit_loc)})
            meta["distance_from_origin_m"] = round(
                math.hypot(hit_loc.x - origin[0], hit_loc.y - origin[1]), 3
            )
            record["hit"] = meta
        rays.append(record)

    # The stationary precheck can pass a set of heights and lateral offsets.
    # A single 2.5 m ray misses a low vehicle body when the stop pose shifts;
    # the extra heights/footprint are stricter checks and do not change the
    # stop threshold.
    for height in heights:
        start = carla.Location(x=front.x, y=front.y, z=loc.z + height)
        for offset in offsets:
            end = carla.Location(
                x=front.x + dir_x * probe_dist + lateral[0] * offset,
                y=front.y + dir_y * probe_dist + lateral[1] * offset,
                z=loc.z + height)
            hit_loc, hit_meta = _cast_for_safety(session, start, end, with_details)
            if hit_loc is not None:
                dist = math.hypot(hit_loc.x - front.x, hit_loc.y - front.y)
                min_hit = dist if min_hit is None else min(min_hit, dist)
            if with_details:
                _record_ray(
                    probe_source, height, offset, start, end, hit_loc, hit_meta,
                    (front.x, front.y),
                )
    # A decision-node precheck also checks the route corridor from the matched
    # node. The vehicle can stop up to the node-match radius away with a
    # different yaw; the node origin is fixed and closes that pose gap.
    for origin_s in origins:
        p0o = point_at_s(points, cum, origin_s)
        p1o = point_at_s(points, cum, min(cum[-1], origin_s + 1.0))
        odx, ody = p1o[0] - p0o[0], p1o[1] - p0o[1]
        olen = math.hypot(odx, ody)
        if olen < 1e-3:
            p0o, p1o = points[-2], points[-1]
            odx, ody = p1o[0] - p0o[0], p1o[1] - p0o[1]
            olen = math.hypot(odx, ody)
        odirx, odiry = odx / olen, ody / olen
        olat = (-odiry, odirx)
        for height in heights:
            start = carla.Location(x=p0o[0], y=p0o[1], z=loc.z + height)
            for offset in offsets:
                end = carla.Location(
                    x=p0o[0] + odirx * probe_dist + olat[0] * offset,
                    y=p0o[1] + odiry * probe_dist + olat[1] * offset,
                    z=loc.z + height)
                hit_loc, hit_meta = _cast_for_safety(session, start, end, with_details)
                if hit_loc is not None:
                    dist = math.hypot(hit_loc.x - p0o[0], hit_loc.y - p0o[1])
                    min_hit = dist if min_hit is None else min(min_hit, dist)
                if with_details:
                    _record_ray(
                        "path_origin", height, offset, start, end, hit_loc,
                        hit_meta, (p0o[0], p0o[1]), origin_s=origin_s,
                    )
    ground = []
    ground_inside_ego = False
    # Probe 3-5 m ahead of the car centre, i.e. beyond the ego footprint, so
    # the vertical ray cannot hit our own roof. Skip samples past the path end.
    # The inside_ego_footprint flag is diagnostic only: it does not change the
    # probe order or the safety verdict in this task.
    for ds in (0.0, 1.0, 2.0):
        sample_s = s + 3.0 + ds
        if sample_s > cum[-1] + 1e-6:
            continue
        p = point_at_s(points, cum, sample_s)
        z = session.floor_at(p[0], p[1], z=floor_probe_z)
        ground.append(z)
        if with_details:
            local_x, local_y = ego_footprint.local_point(
                loc.x, loc.y, ego_yaw, p[0], p[1]
            )
            inside_ego = (
                abs(local_x) <= ego_footprint.half_length
                and abs(local_y) <= ego_footprint.half_width
            )
            ground_inside_ego = ground_inside_ego or inside_ego
            ground_probes.append(
                {
                    "s": round(sample_s, 3),
                    "point": {"x": round(p[0], 3), "y": round(p[1], 3)},
                    "floor_z": z,
                    "inside_ego_footprint": inside_ego,
                    "ego_local": {
                        "x": round(local_x, 3),
                        "y": round(local_y, 3),
                    },
                }
            )
    verdict = forward_safety_verdict(
        min_hit_m=min_hit,
        speed_mps=v,
        ground_z=ground,
        stop_distance_m=stop_distance_m,
    )
    if with_details:
        details_out.clear()
        details_out.update(
            {
                "front": _loc_dict(front),
                "path_point_at_s": {
                    "s": round(s, 3),
                    "x": round(p0[0], 3),
                    "y": round(p0[1], 3),
                },
                "path_point_at_s_plus_1": {
                    "s": round(min(cum[-1], s + 1.0), 3),
                    "x": round(p1[0], 3),
                    "y": round(p1[1], 3),
                },
                "path_tangent": {"dx": round(dir_x, 6), "dy": round(dir_y, 6)},
                "stop_distance_m": round(stop_dist, 3),
                "probe_distance_m": round(probe_dist, 3),
                "heights_m": list(heights),
                "lateral_offsets_m": list(offsets),
                "path_origin_s": list(origins),
                "reverse": bool(reverse),
                "probe_origin": probe_source,
                "rays": rays,
                "ground_probes": ground_probes,
                "ground_probe_inside_ego": bool(ground_inside_ego),
                "verdict": verdict.to_metadata(),
            }
        )
    return verdict.blocked, min_hit, ground


def pure_pursuit(vehicle, points, cum, s, dist_goal):
    st = vehicle.get_transform()
    v = math.hypot(vehicle.get_velocity().x, vehicle.get_velocity().y)
    command, info = pure_pursuit_command(
        x=st.location.x,
        y=st.location.y,
        yaw_rad=math.radians(st.rotation.yaw),
        speed_mps=v,
        points=points,
        cumulative=cum,
        s=s,
        distance_to_goal_m=dist_goal,
    )
    return (
        carla.VehicleControl(
            throttle=command.throttle, steer=command.steer, brake=command.brake
        ),
        info.to_metadata(),
        v,
    )


def run_scenario(session, args, path, points, cum, run_index):
    scenario = args.scenario
    goal = NODES[path[-1]]
    session.destroy_leftovers()
    ego = session.spawn_vehicle(EGO_ROLE, NODES[START_NODE][0], NODES[START_NODE][1], 6.7, 0.0)
    obstacle = None
    if scenario == "obstacle":
        obstacle = session.spawn_vehicle(OBSTACLE_ROLE, -8.0, -7.0, 6.7, 90.0)
    session.tick(40)
    start_pose = state_of(ego, session)
    log("run %d: start=(%.2f,%.2f) goal=(%.2f,%.2f) scenario=%s" % (
        run_index, start_pose["x"], start_pose["y"], goal[0], goal[1], scenario))

    screenshots = []
    latest = None
    if args.screenshots:
        _, latest = session.spawn_chase_camera(ego)
        session.tick(15)  # warm up the camera while the car is stationary
        shot = session.save_latest(latest, "run%d_01_start.png" % run_index)
        if shot:
            screenshots.append(shot)

    records = []
    stop_reason = None
    hit_mid_turn = False
    steps = 0
    max_sim = args.max_sim_seconds
    if scenario == "timeout" and args.max_sim_seconds is None:
        max_sim = 4.0
    if max_sim is None:
        max_sim = 90.0
    max_steps = args.max_steps
    start_t = session.sim_time()
    monitor = SegmentMonitor(
        goal_x=goal[0],
        goal_y=goal[1],
        start_t=start_t,
        max_sim_seconds=max_sim,
    )

    while steps < max_steps:
        st = state_of(ego, session)
        s, px, py, cross = project_to_path(
            points, cum, st["x"], st["y"], monitor.last_progress_s
        )
        dist_goal = math.hypot(st["x"] - goal[0], st["y"] - goal[1])
        blocked, min_hit, ground = safety_check(session, ego, points, cum, s)
        stop_reason = monitor.update(
            t=st["t"],
            x=st["x"],
            y=st["y"],
            speed_mps=st["speed"],
            progress_s=s,
            cross_track_m=cross,
            blocked=blocked,
        )
        if stop_reason is not None:
            break

        control, info, v = pure_pursuit(ego, points, cum, s, dist_goal)
        ego.apply_control(control)
        records.append({
            "step": steps,
            "t": st["t"],
            "x": st["x"],
            "y": st["y"],
            "z": st["z"],
            "yaw": st["yaw"],
            "speed": st["speed"],
            "steer": round(control.steer, 3),
            "throttle": round(control.throttle, 3),
            "brake": round(control.brake, 3),
            "progress_m": round(s, 3),
            "cross_track_m": round(cross, 3),
            "goal_error_m": round(dist_goal, 3),
            "safety_min_m": None if min_hit is None else round(min_hit, 3),
            "ground_z": ground,
            **info,
        })
        session.tick()
        if args.screenshots and not hit_mid_turn and 9.0 < s < 14.0:
            shot = session.save_latest(latest, "run%d_02_turn.png" % run_index)
            if shot:
                screenshots.append(shot)
            hit_mid_turn = True
        steps += 1

    if stop_reason is None:
        stop_reason = "timeout"
    session.brake_to_stop(ego)
    final = state_of(ego, session)
    final_s, _, _, final_cross = project_to_path(points, cum, final["x"], final["y"], 0.0)
    goal_error = math.hypot(final["x"] - goal[0], final["y"] - goal[1])
    yaw_change = (final["yaw"] - start_pose["yaw"] + 180.0) % 360.0 - 180.0
    if args.screenshots:
        shot = session.save_latest(latest, "run%d_03_stop.png" % run_index)
        if shot:
            screenshots.append(shot)
    log("run %d: stop=%s final=(%.2f,%.2f) goal_error=%.2f m progress=%.2f/%.2f steps=%d" % (
        run_index, stop_reason, final["x"], final["y"], goal_error, final_s, cum[-1], steps))

    result = {
        "run": run_index,
        "scenario": scenario,
        "start_pose": start_pose,
        "goal": {"x": goal[0], "y": goal[1]},
        "records": records,
        "final_pose": final,
        "stop_reason": stop_reason,
        "success": stop_reason == "success",
        "goal_error_m": round(goal_error, 3),
        "yaw_change_deg": round(yaw_change, 3),
        "turn_completed": abs(yaw_change) >= 60.0,
        "progress_m": round(final_s, 3),
        "path_length_m": round(cum[-1], 3),
        "steps": steps,
        "sim_seconds": round(session.sim_time() - start_t, 3),
        "screenshots": screenshots,
    }
    if stop_reason == "success" and goal_error > 2.0:
        result["success"] = False
    session.destroy_actors()
    session.tick(2)
    result["leftover_actors"] = session.leftover_count()
    return result


def check_paths(out_dir):
    checks = []
    reachable, status = astar(START_NODE, GOAL_NODE)
    checks.append({"name": "reachable_path", "pass": reachable is not None,
                   "path": reachable, "status": status})
    unreachable, status2 = astar(START_NODE, "isolated")
    checks.append({"name": "unreachable_path", "pass": unreachable is None and status2 == "no_path",
                   "status": status2})
    _, status3 = astar("does_not_exist", GOAL_NODE)
    checks.append({"name": "invalid_start", "pass": status3 == "invalid_start", "status": status3})
    _, status4 = astar(START_NODE, "does_not_exist")
    checks.append({"name": "invalid_target", "pass": status4 == "invalid_target", "status": status4})
    if reachable:
        contiguous = all((reachable[i], reachable[i + 1]) in EDGES or
                         (reachable[i + 1], reachable[i]) in EDGES
                         for i in range(len(reachable) - 1))
        checks.append({"name": "path_edges_contiguous", "pass": contiguous})
    ok = all(c["pass"] for c in checks)
    payload = {"status": "PASS" if ok else "FAIL", "checks": checks, "nodes": NODES, "edges": EDGES}
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "check_paths.json"), "w") as fh:
        json.dump(payload, fh, indent=2)
    for c in checks:
        log("[%s] %s" % ("PASS" if c["pass"] else "FAIL", c["name"]))
    log("RESULT:", payload["status"])
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--scenario", default="nominal",
                        choices=["nominal", "obstacle", "timeout", "unreachable"])
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--max-sim-seconds", type=float, default=None)
    parser.add_argument("--max-steps", type=int, default=3600)
    parser.add_argument("--screenshots", action="store_true")
    parser.add_argument("--check-paths", action="store_true")
    parser.add_argument("--expect", default=None,
                        choices=["success", "obstacle", "timeout", "no_path"])
    args = parser.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = args.output_dir or os.path.join(repo_root, "docs", "evidence", "carla-01b")

    if args.check_paths:
        return check_paths(out_dir)

    path, plan_status = astar(START_NODE, GOAL_NODE if args.scenario != "unreachable" else "isolated")
    expected = args.expect
    if expected is None:
        expected = {"nominal": "success", "obstacle": "obstacle",
                    "timeout": "timeout", "unreachable": "no_path"}[args.scenario]

    results = {
        "meta": {"scenario": args.scenario, "map": MAP_NAME, "start_node": START_NODE,
                 "goal_node": "isolated" if args.scenario == "unreachable" else GOAL_NODE,
                 "expected": expected, "fixed_delta_seconds": FIXED_DT},
        "graph": {"nodes": NODES, "edges": EDGES},
        "planning": {"path": path, "status": plan_status,
                     "path_length_m": None},
        "runs": [],
    }
    if plan_status is not None or path is None:
        results["status"] = "PASS" if plan_status == expected else "FAIL"
        results["checks"] = [{"name": "planning", "pass": results["status"] == "PASS",
                              "detail": plan_status}]
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "result.json"), "w") as fh:
            json.dump(results, fh, indent=2)
        log("planning status:", plan_status, "| RESULT:", results["status"])
        return 0 if results["status"] == "PASS" else 1

    points = path_points(path)
    cum = cumulative_lengths(points)
    results["planning"]["path_length_m"] = round(cum[-1], 3)

    session = Session(args.host, args.port, out_dir)
    exit_code = 1
    try:
        results["meta"]["server_version"] = session.client.get_server_version()
        results["meta"]["map_loaded"] = session.world.get_map().name
        valid, waypoint_report = validate_waypoints(session, path)
        results["waypoint_validation"] = waypoint_report
        if not valid:
            results["planning"]["status"] = "invalid_route_geometry"
            results["status"] = "FAIL"
            with open(os.path.join(out_dir, "result.json"), "w") as fh:
                json.dump(results, fh, indent=2)
            log("waypoint validation failed; refusing to drive")
            return 1

        for i in range(1, args.runs + 1):
            run = run_scenario(session, args, path, points, cum, i)
            if run["records"]:
                plot = os.path.join(out_dir, "run%d_trajectory.png" % i)
                plot_trajectory(points, cum, run["records"], plot)
                run["trajectory_plot"] = plot
                log("  saved", plot)
            results["runs"].append(run)
            actual = run["stop_reason"]
            log("run %d expected=%s actual=%s" % (i, expected, actual))

        actual_last = results["runs"][-1]["stop_reason"]
        results["status"] = "PASS" if actual_last == expected else "FAIL"
        exit_code = 0 if results["status"] == "PASS" else 1
        log("RESULT:", results["status"])
    finally:
        session.close()
        after = session.world.get_settings()
        results["settings"] = {
            "before": session.original,
            "after": {key: getattr(after, key) for key in session.original},
        }
        results["cleanup_after"] = {"leftover_actors": session.leftover_count()}
        checks = [
            {"name": "path_found", "pass": path is not None},
            {"name": "waypoints_valid",
             "pass": bool(results.get("waypoint_validation")) and
                     all(v["ok"] for v in results.get("waypoint_validation", {}).values())},
            {"name": "settings_restored",
             "pass": results["settings"]["before"] == results["settings"]["after"]},
            {"name": "cleanup_no_leftovers",
             "pass": results["cleanup_after"]["leftover_actors"] == 0},
        ]
        if results["runs"]:
            last = results["runs"][-1]
            checks.append({"name": "expected_stop_reason",
                           "pass": last["stop_reason"] == expected,
                           "detail": last["stop_reason"]})
            if args.scenario == "nominal":
                checks.append({"name": "turn_completed", "pass": last.get("turn_completed", False),
                               "detail": last.get("yaw_change_deg")})
                checks.append({"name": "goal_error_within_2m",
                               "pass": last["goal_error_m"] <= 2.0,
                               "detail": last["goal_error_m"]})
        results["checks"] = checks
        if not all(c["pass"] for c in checks):
            results["status"] = "FAIL"
            exit_code = 1
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "result.json"), "w") as fh:
            json.dump(results, fh, indent=2)
        log("wrote", os.path.join(out_dir, "result.json"))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
