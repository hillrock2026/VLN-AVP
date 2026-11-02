"""Scene-geometry candidate generation for parking-target binding.

The VLM never supplies a coordinate and never supplies a bay id. It may only
name a temporary candidate label that this module painted on the real frame.
Everything here is derived from the measured bay geometry and the real camera
pose:

* :class:`BayEntity` - the known bay polygons/slot nodes from
  :mod:`vln.carla.parking_verdict`;
* :func:`project_bay` - a pin-hole projection of those polygons with the
  horizontal-FOV intrinsics used by the real ``sensor.camera.rgb`` frames;
* :func:`visible_candidates` - only bays whose whole polygon is inside the
  frame, ordered and labelled deterministically;
* :func:`classify_side` - the bay's left/right/ahead relation to the real ego
  heading, used as a system-side filter for a natural-language side request.

This module deliberately does not import ``carla``: the runnable script reads
``camera.get_transform()`` and constructs :class:`CameraPose` from it. The
projection formula is regression-tested against real camera corners measured
in the CARLA map (``tests/vln/test_parking_entities.py``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .parking_verdict import (
    BAY03_CENTER,
    BAY03_ID,
    BAY03_POLYGON,
    BAY11_CENTER,
    BAY11_ID,
    BAY11_POLYGON,
    BAY11_SLOT_NODE_ID,
    PARKING_SLOT_NODE_ID,
)

__all__ = [
    "BayEntity",
    "BAY_ENTITIES",
    "bay_entity",
    "entity_for_slot_node",
    "CameraPose",
    "ProjectedBay",
    "EgoPose2D",
    "SIDE_BEHIND",
    "SIDE_LEFT",
    "SIDE_RIGHT",
    "SIDE_AHEAD",
    "LABELS",
    "project_point",
    "project_bay",
    "visible_candidates",
    "assign_labels",
    "classify_side",
    "CANDIDATE_ORDER_NEAR_TO_FAR",
    "CANDIDATE_ORDER_FAR_TO_NEAR",
    "CANDIDATE_ORDER_BAY_ID",
]


@dataclass(frozen=True)
class BayEntity:
    """One known parking bay, independent of any camera or model output."""

    bay_id: str
    slot_node_id: str
    polygon: tuple[tuple[float, float], ...]
    center: tuple[float, float]


BAY_ENTITIES = (
    BayEntity(BAY03_ID, PARKING_SLOT_NODE_ID, BAY03_POLYGON, BAY03_CENTER),
    BayEntity(BAY11_ID, BAY11_SLOT_NODE_ID, BAY11_POLYGON, BAY11_CENTER),
)

_BY_ID = {entity.bay_id: entity for entity in BAY_ENTITIES}
_BY_SLOT = {entity.slot_node_id: entity for entity in BAY_ENTITIES}


def bay_entity(bay_id: str) -> BayEntity:
    try:
        return _BY_ID[bay_id]
    except KeyError:
        raise KeyError(f"unknown bay id {bay_id!r}") from None


def entity_for_slot_node(slot_node_id: str) -> BayEntity:
    try:
        return _BY_SLOT[slot_node_id]
    except KeyError:
        raise KeyError(f"no bay entity for slot node {slot_node_id!r}") from None


@dataclass(frozen=True)
class CameraPose:
    """A real camera pose in CARLA world coordinates (UE basis)."""

    x: float
    y: float
    z: float
    yaw_deg: float
    pitch_deg: float = 0.0
    roll_deg: float = 0.0

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.z, self.yaw_deg, self.pitch_deg, self.roll_deg)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("camera pose values must be finite")

    def basis(self) -> tuple[tuple[float, float, float], ...]:
        yaw = math.radians(self.yaw_deg)
        pitch = math.radians(self.pitch_deg)
        roll = math.radians(self.roll_deg)
        cy, sy = math.cos(yaw), math.sin(yaw)
        cp, sp = math.cos(pitch), math.sin(pitch)
        forward = (cp * cy, cp * sy, sp)
        right = (-sy, cy, 0.0)
        up = _cross(forward, right)
        if roll:
            right, up = _rotate_about(right, forward, roll), _rotate_about(
                up, forward, roll
            )
        return forward, right, up


@dataclass(frozen=True)
class EgoPose2D:
    """The real ego pose used for the left/right filter."""

    x: float
    y: float
    yaw_deg: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) for v in (self.x, self.y, self.yaw_deg)):
            raise ValueError("ego pose values must be finite")


SIDE_LEFT = "LEFT"
SIDE_RIGHT = "RIGHT"
SIDE_AHEAD = "AHEAD"
SIDE_BEHIND = "BEHIND"

LABELS = "ABCDEFGH"

CANDIDATE_ORDER_NEAR_TO_FAR = "near_to_far"
CANDIDATE_ORDER_FAR_TO_NEAR = "far_to_near"
CANDIDATE_ORDER_BAY_ID = "bay_id"
_CANDIDATE_ORDERS = frozenset(
    {
        CANDIDATE_ORDER_NEAR_TO_FAR,
        CANDIDATE_ORDER_FAR_TO_NEAR,
        CANDIDATE_ORDER_BAY_ID,
    }
)


@dataclass(frozen=True)
class ProjectedBay:
    """One bay projected into the current real frame."""

    entity: BayEntity
    corners: tuple[tuple[float, float], ...]
    depths: tuple[float, ...]
    visible_corners: int
    all_in_frame: bool
    bbox: tuple[float, float, float, float]
    center_image: tuple[float, float]
    distance_m: float
    side: str
    bearing_deg: float
    label: str = ""


def _cross(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _rotate_about(
    vector: tuple[float, float, float],
    axis: tuple[float, float, float],
    angle: float,
) -> tuple[float, float, float]:
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    cross = _cross(axis, vector)
    dot = sum(a * b for a, b in zip(axis, vector))
    return tuple(
        vector[i] * cos_a + cross[i] * sin_a + axis[i] * dot * (1.0 - cos_a)
        for i in range(3)
    )


def project_point(
    pose: CameraPose,
    point: tuple[float, float, float],
    *,
    fov_deg: float,
    width: int,
    height: int,
) -> Optional[tuple[float, float, float]]:
    """Project one world point; return ``(u, v, depth)`` or ``None``."""

    if not math.isfinite(fov_deg) or not 0.0 < fov_deg < 180.0:
        raise ValueError("fov_deg must be finite and in (0, 180)")
    if type(width) is not int or type(height) is not int or width < 1 or height < 1:
        raise ValueError("width and height must be positive integers")
    if len(point) != 3 or not all(math.isfinite(v) for v in point):
        raise ValueError("point must be a finite 3-tuple")
    forward, right, up = pose.basis()
    delta = (point[0] - pose.x, point[1] - pose.y, point[2] - pose.z)
    depth = sum(a * b for a, b in zip(delta, forward))
    if depth <= 0.05:
        return None
    lateral = sum(a * b for a, b in zip(delta, right))
    vertical = sum(a * b for a, b in zip(delta, up))
    focal = (width / 2.0) / math.tan(math.radians(fov_deg) / 2.0)
    return (
        width / 2.0 + focal * lateral / depth,
        height / 2.0 - focal * vertical / depth,
        depth,
    )


def classify_side(
    entity: BayEntity, ego: EgoPose2D, *, ahead_half_angle_deg: float = 30.0
) -> tuple[str, float, float]:
    """Classify a bay centre relative to the real ego heading.

    Returns ``(side, bearing_deg, distance_m)``. A bearing within
    ``±ahead_half_angle_deg`` is AHEAD; beyond that the sign of the lateral
    component decides LEFT/RIGHT. A bay behind the ego is BEHIND regardless of
    its lateral offset.
    """

    if not math.isfinite(ahead_half_angle_deg) or not (
        0.0 < ahead_half_angle_deg < 90.0
    ):
        raise ValueError("ahead_half_angle_deg must be in (0, 90)")
    yaw = math.radians(ego.yaw_deg)
    forward = (math.cos(yaw), math.sin(yaw))
    right = (-math.sin(yaw), math.cos(yaw))
    dx = entity.center[0] - ego.x
    dy = entity.center[1] - ego.y
    forward_component = dx * forward[0] + dy * forward[1]
    lateral_component = dx * right[0] + dy * right[1]
    distance = math.hypot(dx, dy)
    bearing = math.degrees(math.atan2(lateral_component, forward_component))
    if forward_component <= 0.0:
        side = SIDE_BEHIND
    elif abs(bearing) <= ahead_half_angle_deg:
        side = SIDE_AHEAD
    elif bearing > 0.0:
        side = SIDE_RIGHT
    else:
        side = SIDE_LEFT
    return side, bearing, distance


def project_bay(
    entity: BayEntity,
    pose: CameraPose,
    *,
    fov_deg: float,
    width: int,
    height: int,
    floor_z: float,
    ego: EgoPose2D,
) -> ProjectedBay:
    """Project the whole bay polygon and measure how much is inside the frame."""

    if not math.isfinite(floor_z):
        raise ValueError("floor_z must be finite")
    corners = []
    depths = []
    visible = 0
    for x, y in entity.polygon:
        projected = project_point(
            pose, (x, y, floor_z), fov_deg=fov_deg, width=width, height=height
        )
        if projected is None:
            depths.append(-1.0)
            corners.append((float("nan"), float("nan")))
            continue
        u, v, depth = projected
        depths.append(depth)
        corners.append((u, v))
        if 0.0 <= u < width and 0.0 <= v < height:
            visible += 1
    if visible:
        inside = [corner for corner in corners if math.isfinite(corner[0])]
    else:
        inside = []
    if inside:
        us = [corner[0] for corner in inside]
        vs = [corner[1] for corner in inside]
        bbox = (min(us), min(vs), max(us), max(vs))
        center_image = (sum(us) / len(us), sum(vs) / len(vs))
    else:
        bbox = (float("nan"), float("nan"), float("nan"), float("nan"))
        center_image = (float("nan"), float("nan"))
    distance = math.hypot(entity.center[0] - pose.x, entity.center[1] - pose.y)
    side, bearing, _ = classify_side(entity, ego)
    return ProjectedBay(
        entity=entity,
        corners=tuple(corners),
        depths=tuple(depths),
        visible_corners=visible,
        all_in_frame=visible == len(entity.polygon),
        bbox=bbox,
        center_image=center_image,
        distance_m=distance,
        side=side,
        bearing_deg=bearing,
    )


def visible_candidates(
    pose: CameraPose,
    ego: EgoPose2D,
    *,
    fov_deg: float,
    width: int,
    height: int,
    floor_z: float,
    entities: tuple[BayEntity, ...] = BAY_ENTITIES,
    min_visible_corners: int = 4,
    order: str = CANDIDATE_ORDER_NEAR_TO_FAR,
) -> tuple[ProjectedBay, ...]:
    """Return fully projected, labelled candidates in a deterministic order.

    ``min_visible_corners`` defaults to the polygon vertex count, i.e. a
    candidate is usable only when its whole region is in the frame. Partial
    visibility is still available from :func:`project_bay` so a caller can
    distinguish "not visible" from "partly cut off".
    """

    if type(min_visible_corners) is not int or min_visible_corners < 3:
        raise ValueError("min_visible_corners must be an integer >= 3")
    projected = [
        project_bay(
            entity,
            pose,
            fov_deg=fov_deg,
            width=width,
            height=height,
            floor_z=floor_z,
            ego=ego,
        )
        for entity in entities
    ]
    selected = [
        item
        for item in projected
        if item.visible_corners >= min(min_visible_corners, len(item.entity.polygon))
    ]
    if len(selected) > len(LABELS):
        raise ValueError(
            f"{len(selected)} candidates exceed the {len(LABELS)} labels available"
        )
    return assign_labels(selected, order=order)


def assign_labels(
    projected: list[ProjectedBay], *, order: str = CANDIDATE_ORDER_NEAR_TO_FAR
) -> tuple[ProjectedBay, ...]:
    """Assign A/B/... to projected bays.

    ``near_to_far`` is the production order. The other orders exist so tests can
    prove that identity is carried by ``bay_id`` and not by the temporary
    letter: permuting the letters must not change the bound bay.
    """

    if order not in _CANDIDATE_ORDERS:
        raise ValueError(
            f"unknown candidate order {order!r}; expected one of "
            f"{sorted(_CANDIDATE_ORDERS)}"
        )
    if order == CANDIDATE_ORDER_NEAR_TO_FAR:
        ordered = sorted(projected, key=lambda item: item.distance_m)
    elif order == CANDIDATE_ORDER_FAR_TO_NEAR:
        ordered = sorted(projected, key=lambda item: -item.distance_m)
    else:
        ordered = sorted(projected, key=lambda item: item.entity.bay_id)
    return tuple(
        ProjectedBay(
            entity=item.entity,
            corners=item.corners,
            depths=item.depths,
            visible_corners=item.visible_corners,
            all_in_frame=item.all_in_frame,
            bbox=item.bbox,
            center_image=item.center_image,
            distance_m=item.distance_m,
            side=item.side,
            bearing_deg=item.bearing_deg,
            label=LABELS[index],
        )
        for index, item in enumerate(ordered)
    )
