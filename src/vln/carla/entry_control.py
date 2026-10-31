"""Bounded low-speed command for one Entry segment.

The existing validated ``parking_track_command`` is reused unchanged: it
combines the 3.56 m arc curvature feed-forward, signed lateral correction and
heading correction. This wrapper only adds the per-segment stop/speed budget
and the terminal approach cap. It never takes a model value and never changes
the shared controller gains or safety thresholds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from vln.carla.parking_control import parking_track_command
from vln.carla.route_control import ControlCommand, PurePursuitInfo
from vln.parking.entry import EntryRoute, EntryRouteSegment

__all__ = ["EntrySegmentCommand", "entry_segment_command", "ENTRY_SPEED_CAP_MPS"]

ENTRY_SPEED_CAP_MPS = 0.35


@dataclass(frozen=True)
class EntrySegmentCommand:
    command: ControlCommand
    info: PurePursuitInfo
    signed_lateral_m: float
    cross_track_m: float
    distance_to_segment_end_m: float
    distance_to_slot_m: float
    speed_cap_mps: float
    final_leg: bool

    def to_metadata(self) -> dict:
        return {
            "throttle": round(self.command.throttle, 4),
            "brake": round(self.command.brake, 4),
            "steer": round(self.command.steer, 4),
            "lookahead_m": round(self.info.lookahead_m, 4),
            "signed_lateral_m": round(self.signed_lateral_m, 4),
            "cross_track_m": round(self.cross_track_m, 4),
            "distance_to_segment_end_m": round(self.distance_to_segment_end_m, 4),
            "distance_to_slot_m": round(self.distance_to_slot_m, 4),
            "speed_cap_mps": round(self.speed_cap_mps, 4),
            "final_leg": self.final_leg,
        }


def entry_segment_command(
    route: EntryRoute,
    segment: EntryRouteSegment,
    *,
    x: float,
    y: float,
    yaw_rad: float,
    speed_mps: float,
    s: float,
    cross_track_m: float,
    speed_cap_mps: float = ENTRY_SPEED_CAP_MPS,
) -> EntrySegmentCommand:
    if not isinstance(route, EntryRoute):
        raise TypeError("route must be an EntryRoute")
    if not isinstance(segment, EntryRouteSegment):
        raise TypeError("segment must be an EntryRouteSegment")
    for name, value in (
        ("x", x),
        ("y", y),
        ("yaw_rad", yaw_rad),
        ("speed_mps", speed_mps),
        ("s", s),
        ("cross_track_m", cross_track_m),
    ):
        if not math.isfinite(float(value)):
            raise ValueError(f"{name} must be finite")
    if speed_mps < 0.0:
        raise ValueError("speed_mps must be non-negative")
    if s < 0.0:
        raise ValueError("s must be non-negative")

    s = max(0.0, min(route.length_m, float(s)))
    tangent = route.tangent_at_s(s)
    px, py = route.point_at_s(s)
    tang_x, tang_y = math.cos(tangent), math.sin(tangent)
    signed_lateral = -((x - px) * tang_y - (y - py) * tang_x)
    segment_remaining = max(0.0, segment.end_s - s)
    distance_to_slot = math.hypot(
        route.target_pose[0] - x, route.target_pose[1] - y
    )
    final_leg = segment.index == len(route.segments) or s >= route.length_m - 2.0
    speed_cap = float(speed_cap_mps)
    if not math.isfinite(speed_cap) or speed_cap <= 0.0:
        raise ValueError("speed_cap_mps must be a positive finite number")
    # Slow down inside the last metre of the segment to a controlled stop.
    approach_remaining = distance_to_slot if final_leg else segment_remaining
    if approach_remaining < 1.0:
        speed_cap = min(
            speed_cap, max(0.10, speed_cap * max(approach_remaining, 0.05))
        )
    command, info = parking_track_command(
        x=x,
        y=y,
        yaw_rad=yaw_rad,
        speed_mps=speed_mps,
        points=route.points,
        cumulative=route.cumulative,
        s=s,
        distance_to_slot_m=max(0.0, segment_remaining),
        signed_lateral_m=signed_lateral,
        speed_cap_mps=speed_cap,
        cross_gain=2.5 if final_leg else 1.5,
        heading_gain=0.3 if final_leg else 0.1,
    )
    return EntrySegmentCommand(
        command=command,
        info=info,
        signed_lateral_m=signed_lateral,
        cross_track_m=float(cross_track_m),
        distance_to_segment_end_m=segment_remaining,
        distance_to_slot_m=distance_to_slot,
        speed_cap_mps=speed_cap,
        final_leg=final_leg,
    )
