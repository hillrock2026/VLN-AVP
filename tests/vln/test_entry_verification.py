"""Entry authorization and independent verifier tests (CAP-07B-04)."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from vln.carla.entry_scene import bay03_entry_route
from vln.parking.entry import (
    ALIGNMENT_COMPLETED_STAGE,
    AlignmentCompletion,
    EntryAuthorization,
    EntryAuthorizationError,
    EntryBudget,
    EntryGeometryError,
    EntryStage,
    EntryStability,
    EntryTolerances,
    authorize_entry,
    compute_alignment_completion_id,
    consume_entry_authorization,
    entry_authorization_from_metadata,
    measure_entry,
    require_entry_authorization,
    revoke_entry_authorization,
    verify_entry,
)
from vln.parking.alignment import AlignmentAuthorization

NOW = "2026-10-30T12:00:00+00:00"
START = (-3.9959, -17.1843, math.radians(-89.5386))


class _Binding:
    status = "bound"
    bay_id = "bay03"
    slot_node_id = "park_slot"


def _route():
    route, _ = bay03_entry_route(
        task_id="cap07b-04", actual_pose=START, obstacle_points=()
    )
    return route


def _completion(route, **overrides):
    values = dict(
        task_id="cap07b-03",
        target_id="bay03",
        bay_id="bay03",
        slot_node_id="park_slot",
        approach_node_id="park_entry",
        final_pose=route.start_pose,
        final_speed_mps=0.0,
        verification_stage=ALIGNMENT_COMPLETED_STAGE,
        alignment_authorization_id="a" * 64,
        alignment_result_sha256="r" * 64,
        alignment_authorization_sha256="s" * 64,
        created_at=NOW,
    )
    values.update(overrides)
    values["completion_id"] = compute_alignment_completion_id(
        task_id=values["task_id"],
        target_id=values["target_id"],
        bay_id=values["bay_id"],
        slot_node_id=values["slot_node_id"],
        approach_node_id=values["approach_node_id"],
        final_pose={"x": values["final_pose"][0], "y": values["final_pose"][1], "yaw": values["final_pose"][2]},
        final_speed_mps=values["final_speed_mps"],
        verification_stage=values["verification_stage"],
        alignment_authorization_id=values["alignment_authorization_id"],
        alignment_result_sha256=values["alignment_result_sha256"],
        alignment_authorization_sha256=values["alignment_authorization_sha256"],
    )
    return AlignmentCompletion(**values)


def _authorized(route=None, completion=None, **kwargs):
    route = route or _route()
    completion = completion or _completion(route)
    values = dict(
        completion=completion,
        route=route,
        binding=_Binding(),
        task_id="cap07b-04",
        now=NOW,
        ttl_s=600.0,
        budget=EntryBudget(),
        actual_pose=route.start_pose,
    )
    values.update(kwargs)
    authorization = authorize_entry(**values)
    return consume_entry_authorization(
        authorization,
        task_id="cap07b-04",
        bay_id=route.bay_id,
        slot_node_id=route.slot_node_id,
        approach_node_id=route.approach_node_id,
        route_id=route.route_id,
        route_hash=route.route_hash,
        now=NOW,
    )


def _measure(route, x, y, yaw, *, s, speed=0.0, stopped=True, stable=True,
             cross=0.0, collision=0):
    return measure_entry(
        route,
        x=x,
        y=y,
        yaw_rad=yaw,
        speed_mps=speed,
        stopped=stopped,
        route_s=s,
        cross_track_m=cross,
        stability=EntryStability(3, 0.0, 0.0, stable),
        collision_count=collision,
    )


def _terminal(route, **kwargs):
    return _measure(
        route,
        route.target_pose[0],
        route.target_pose[1],
        route.target_heading_rad,
        s=route.length_m,
        **kwargs,
    )


def _verify(route, auth, measurement, *, collision=0, now=NOW, completion=None):
    return verify_entry(
        route,
        completion or _completion(route),
        auth,
        binding=_Binding(),
        measurement=measurement,
        collision_count=collision,
        now=now,
    )


def test_valid_alignment_completion_issues_entry_only_permission() -> None:
    route = _route()
    authorization = _authorized(route)
    assert authorization.decision == "ENTRY_AUTHORIZED"
    assert authorization.permits_entry
    assert authorization.permits_alignment is False
    assert authorization.permits_parking_arc is False
    assert authorization.permits_parking_completed is False
    assert authorization.executes_motion is False
    assert authorization.consumed_at == NOW
    assert authorization.route_hash == route.route_hash
    assert authorization.alignment_final_pose == route.start_pose
    metadata = authorization.to_metadata()
    assert metadata["stage_scope"] == "ENTRY"
    assert metadata["single_use"] is True
    assert metadata["permits_parking_completed"] is False


def test_missing_completion_or_wrong_type_is_refused() -> None:
    route = _route()
    with pytest.raises(TypeError):
        authorize_entry(
            None,
            route,
            binding=_Binding(),
            task_id="cap07b-04",
            now=NOW,
        )
    with pytest.raises(TypeError):
        authorize_entry(
            AlignmentAuthorization,
            route,
            binding=_Binding(),
            task_id="cap07b-04",
            now=NOW,
        )


def test_alignment_stage_must_be_alignment_completed() -> None:
    route = _route()
    with pytest.raises(EntryGeometryError):
        _completion(route, verification_stage="ENTRY_COMPLETED")


def test_completion_id_tamper_is_refused() -> None:
    route = _route()
    completion = _completion(route)
    with pytest.raises(EntryGeometryError):
        replace(completion, completion_id="0" * 64)


def test_binding_and_pose_mismatch_are_refused() -> None:
    route = _route()
    completion = _completion(route)

    class OtherBinding:
        status = "bound"
        bay_id = "bay11"
        slot_node_id = "bay11_slot"

    with pytest.raises(ValueError):
        authorize_entry(
            completion,
            route,
            binding=OtherBinding(),
            task_id="cap07b-04",
            now=NOW,
            actual_pose=route.start_pose,
        )
    far = (route.start_pose[0] + 0.5, route.start_pose[1], route.start_pose[2])
    with pytest.raises(ValueError):
        authorize_entry(
            completion,
            route,
            binding=_Binding(),
            task_id="cap07b-04",
            now=NOW,
            actual_pose=far,
        )


def test_stale_alignment_completion_is_refused() -> None:
    route = _route()
    completion = _completion(route, created_at="2026-10-28T00:00:00+00:00")
    with pytest.raises(ValueError):
        _authorized(route, completion=completion, now=NOW)


def test_entry_requires_its_own_task_id() -> None:
    route = _route()
    completion = _completion(route)
    with pytest.raises(ValueError):
        authorize_entry(
            completion,
            route,
            binding=_Binding(),
            task_id="cap07b-03",
            now=NOW,
            actual_pose=route.start_pose,
        )


def test_permission_is_single_use_and_expires() -> None:
    route = _route()
    authorization = _authorized(route)
    assert authorization.is_active(
        task_id="cap07b-04",
        bay_id="bay03",
        slot_node_id="park_slot",
        approach_node_id="park_entry",
        route_id=route.route_id,
        route_hash=route.route_hash,
        now=NOW,
    )
    with pytest.raises(EntryAuthorizationError):
        consume_entry_authorization(
            authorization,
            task_id="cap07b-04",
            bay_id="bay03",
            slot_node_id="park_slot",
            approach_node_id="park_entry",
            route_id=route.route_id,
            route_hash=route.route_hash,
            now=NOW,
        )
    expired = _authorized(route, ttl_s=60.0)
    assert not expired.is_active(
        task_id="cap07b-04",
        bay_id="bay03",
        slot_node_id="park_slot",
        approach_node_id="park_entry",
        route_id=route.route_id,
        route_hash=route.route_hash,
        now="2026-10-30T12:02:00+00:00",
    )


def test_revocation_blocks_entry() -> None:
    route = _route()
    authorization = _authorized(route)
    revoked = revoke_entry_authorization(authorization, "operator", now=NOW)
    assert revoked.revoked
    result = _verify(route, revoked, _terminal(route))
    assert result.stage == EntryStage.REJECTED
    assert "entry_authorization_inactive" in result.reasons


def test_route_hash_and_identity_mismatch_are_rejected() -> None:
    route = _route()
    authorization = _authorized(route)
    tampered = replace(authorization, route_hash="0" * 64)
    result = _verify(route, tampered, _terminal(route))
    assert result.stage == EntryStage.REJECTED
    assert "route_identity_mismatch" in result.reasons


def test_alignment_permission_cannot_replace_entry_permission() -> None:
    route = _route()
    # A CAP-07B-03-style alignment permission is not an EntryAuthorization.
    class FakeAlignment:
        permits_entry = True
        decision = "ALIGNMENT_AUTHORIZED"

    with pytest.raises(EntryAuthorizationError):
        require_entry_authorization(
            FakeAlignment(),
            task_id="cap07b-04",
            bay_id="bay03",
            slot_node_id="park_slot",
            approach_node_id="park_entry",
            route_id=route.route_id,
            route_hash=route.route_hash,
            now=NOW,
        )


def test_terminal_state_completes_entry() -> None:
    route = _route()
    authorization = _authorized(route)
    result = _verify(route, authorization, _terminal(route))
    assert result.stage == EntryStage.COMPLETED
    assert result.completed
    assert result.entry_valid
    assert result.reasons == ()
    assert result.checks["footprint_inside_bay"] is True
    assert result.checks["boundary_clearance"] is True
    assert result.checks["no_collision"] is True


def test_start_and_mid_route_are_pending_not_completed() -> None:
    route = _route()
    authorization = _authorized(route)
    start = _measure(route, *START, s=0.0)
    result = _verify(route, authorization, start)
    assert result.stage == EntryStage.PENDING
    assert not result.completed
    mid = route.point_at_s(4.0)
    mid_measure = _measure(
        route, mid[0], mid[1], route.tangent_at_s(4.0), s=4.0
    )
    result = _verify(route, authorization, mid_measure)
    assert result.stage == EntryStage.PENDING
    assert not result.completed


def test_reference_only_in_bay_is_not_entry_complete() -> None:
    route = _route()
    authorization = _authorized(route)
    # Reference at the bay opening, footprint sticking east outside the bay.
    measurement = _measure(
        route, -4.0, -21.0, math.pi, s=route.length_m
    )
    result = _verify(route, authorization, measurement)
    assert result.stage in (EntryStage.PENDING, EntryStage.SAFE_STOP)
    assert result.checks["footprint_inside_bay"] is False
    assert not result.completed


def test_heading_over_tolerance_is_not_complete() -> None:
    route = _route()
    authorization = _authorized(route)
    # A 5.1 deg residual at the bay centre line: the whole footprint still
    # fits inside the bay, but the heading tolerance is exceeded.
    yaw = route.target_heading_rad + math.radians(5.1)
    measurement = _measure(
        route,
        route.target_pose[0],
        route.target_pose[1] + 0.15,
        yaw,
        s=route.length_m,
    )
    result = _verify(route, authorization, measurement)
    assert result.stage == EntryStage.PENDING
    assert result.checks["terminal_heading"] is False
    assert not result.completed


def test_boundary_clearance_failure_is_not_complete() -> None:
    route = _route()
    authorization = _authorized(route)
    measurement = _measure(
        route,
        route.target_pose[0],
        route.target_pose[1] - 0.15,
        route.target_heading_rad,
        s=route.length_m,
    )
    result = _verify(route, authorization, measurement)
    assert result.stage == EntryStage.PENDING
    assert (
        result.checks["footprint_inside_bay"] is False
        or result.checks["boundary_clearance"] is False
    )
    assert not result.completed


def test_collision_is_safe_stop() -> None:
    route = _route()
    authorization = _authorized(route)
    result = _verify(route, authorization, _terminal(route), collision=1)
    assert result.stage == EntryStage.SAFE_STOP
    assert "no_collision" in result.reasons


def test_not_stopped_is_safe_stop() -> None:
    route = _route()
    authorization = _authorized(route)
    measurement = _terminal(route, speed=0.3, stopped=False)
    result = _verify(route, authorization, measurement)
    assert result.stage == EntryStage.SAFE_STOP
    assert "stopped" in result.reasons


def test_unstable_stop_is_valid_not_completed() -> None:
    route = _route()
    authorization = _authorized(route)
    measurement = _terminal(route, stable=False)
    result = _verify(route, authorization, measurement)
    assert result.stage == EntryStage.VALID
    assert result.entry_valid
    assert not result.completed


def test_route_deviation_is_safe_stop() -> None:
    route = _route()
    authorization = _authorized(route)
    measurement = _terminal(route, cross=0.80)
    result = _verify(route, authorization, measurement)
    assert result.stage == EntryStage.SAFE_STOP
    assert "route_deviation" in result.reasons


def test_obstacle_inside_terminal_footprint_is_safe_stop() -> None:
    route = _route()
    route = replace(
        route,
        obstacle_points=((-9.5, -22.30),),
    )
    authorization = _authorized(route)
    measurement = _terminal(route)
    result = _verify(route, authorization, measurement)
    assert result.stage == EntryStage.SAFE_STOP
    assert "obstacle_clearance" in result.reasons


def test_missing_measurement_or_completion_is_rejected() -> None:
    route = _route()
    authorization = _authorized(route)
    result = verify_entry(
        route,
        _completion(route),
        authorization,
        binding=_Binding(),
        measurement=None,
        now=NOW,
    )
    assert result.stage == EntryStage.REJECTED
    assert result.reasons == ("vehicle_state_missing",)
    result = verify_entry(
        None,
        None,
        authorization,
        binding=_Binding(),
        now=NOW,
        geometry_error="route_missing",
    )
    assert result.stage == EntryStage.REJECTED


def test_metadata_round_trip_preserves_entry_scope() -> None:
    route = _route()
    authorization = _authorized(route)
    parsed = entry_authorization_from_metadata(authorization.to_metadata())
    assert parsed.authorization_id == authorization.authorization_id
    assert parsed.permits_entry
    assert parsed.permits_alignment is False
    assert parsed.permits_parking_completed is False
    assert parsed.route_hash == route.route_hash


def test_entry_tolerances_are_the_predeclared_values() -> None:
    tol = EntryTolerances()
    assert tol.position_m == 0.25
    assert tol.heading_deg == 5.0
    assert tol.boundary_clearance_m == 0.05
    assert tol.obstacle_clearance_m == 0.20
    assert tol.route_deviation_m == 0.50
    assert tol.stable_samples == 3
