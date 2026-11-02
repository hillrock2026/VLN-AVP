"""Parking pose refinement geometry, path and authorization tests (CAP-07B-05)."""

from __future__ import annotations

import math

import pytest

from vln.carla.parking_verdict import BAY03_CENTER, BAY03_POLYGON, PARKING_FOOTPRINT
from vln.carla.refinement_plan import (
    build_refinement_phase_plan,
    plan_refinement_path,
)
from vln.parking.refinement import (
    RefinementBudget,
    RefinementStage,
    RefinementStability,
    RefinementTolerances,
    authorize_refinement,
    compute_entry_completion_id,
    consume_refinement_authorization,
    generate_candidates,
    measure_refinement,
    no_safe_refinement_result,
    refinement_phase_improved,
    revoke_refinement_authorization,
    verify_refinement,
)

NOW = "2026-10-30T16:00:00+00:00"
ENTRY_COMPLETION_ID = "e" * 64
ENTRY_AUTH_ID = "a" * 64
BAY = tuple((float(x), float(y)) for x, y in BAY03_POLYGON)
CENTER = (float(BAY03_CENTER[0]), float(BAY03_CENTER[1]))


def _measure(
    x=-9.4864,
    y=-21.2488,
    yaw_deg=-176.5466,
    *,
    speed=0.0,
    stopped=True,
    stable=True,
    collision=0,
    obstacles=(),
):
    return measure_refinement(
        x=x,
        y=y,
        yaw_rad=math.radians(yaw_deg),
        speed_mps=speed,
        stopped=stopped,
        center=CENTER,
        bay_heading_rad=math.pi,
        bay_polygon=BAY,
        footprint=PARKING_FOOTPRINT,
        obstacle_points=obstacles,
        stability=RefinementStability(5, 0.0, 0.0, stable),
        collision_count=collision,
    )


def _selection(current=None, *, obstacles=(), center=CENTER, bay=BAY):
    current = current or _measure(obstacles=obstacles)
    return generate_candidates(
        current_x=current.x,
        current_y=current.y,
        current_heading_rad=current.yaw_rad,
        center=center,
        bay_heading_rad=math.pi,
        bay_polygon=bay,
        footprint=PARKING_FOOTPRINT,
        obstacle_points=obstacles,
        tolerances=RefinementTolerances(),
    )


def _plan(current=None, selected=None, *, obstacles=(), bay=BAY, center=CENTER):
    current = current or _measure(obstacles=obstacles)
    selected = selected or _selection(
        current, obstacles=obstacles, center=center, bay=bay
    ).selected
    return plan_refinement_path(
        current,
        selected,
        bay_polygon=bay,
        bay_center=center,
        footprint=PARKING_FOOTPRINT,
        obstacle_points=obstacles,
        tolerances=RefinementTolerances(),
    )


def _authorized(plan, current=None, **kwargs):
    current = current or _measure()
    values = dict(
        task_id="cap07b-05",
        bay_id="bay03",
        slot_node_id="park_slot",
        entry_completion_id=ENTRY_COMPLETION_ID,
        entry_authorization_id=ENTRY_AUTH_ID,
        start_pose=(current.x, current.y, current.yaw_rad),
        target_pose=(plan.target.x, plan.target.y, plan.target.heading_rad),
        plan_hash=plan.plan_hash,
        tolerances=RefinementTolerances(),
        budget=RefinementBudget(),
        now=NOW,
    )
    values.update(kwargs)
    authorization = authorize_refinement(**values)
    return consume_refinement_authorization(
        authorization,
        task_id="cap07b-05",
        bay_id="bay03",
        slot_node_id="park_slot",
        entry_completion_id=ENTRY_COMPLETION_ID,
        plan_hash=plan.plan_hash,
        now=NOW,
    )


def _verify(authorization, plan, measurement, *, collision=0, now=NOW):
    return verify_refinement(
        task_id="cap07b-05",
        bay_id="bay03",
        slot_node_id="park_slot",
        entry_completion_id=ENTRY_COMPLETION_ID,
        plan_hash=plan.plan_hash,
        authorization=authorization,
        measurement=measurement,
        tolerances=RefinementTolerances(),
        now=now,
    )


def test_current_pose_has_tight_boundary_and_three_degree_heading() -> None:
    current = _measure()
    assert current.footprint_inside_bay
    assert current.boundary_clearance_m == pytest.approx(0.052, abs=1e-3)
    assert current.heading_error_deg == pytest.approx(3.4534, abs=1e-3)
    assert current.distance_to_center_m == pytest.approx(0.1096, abs=1e-3)


def test_candidate_grid_selects_the_bay_centre_and_west_heading() -> None:
    selection = _selection()
    assert selection.ok, selection.reasons
    selected = selection.selected
    assert selected.x == pytest.approx(-9.5)
    assert selected.y == pytest.approx(-21.14)
    assert selected.heading_error_deg == pytest.approx(0.0)
    assert selected.boundary_clearance_m >= 0.30
    assert selected.footprint_inside_bay


def test_candidate_rejects_footprint_outside_bay() -> None:
    # Centre near the east opening: the 5 m footprint crosses the bay boundary.
    selection = _selection(center=(-4.5, -21.14))
    assert not selection.ok
    assert any(
        "footprint_not_inside_bay" in candidate.reasons
        for candidate in selection.candidates
    )


def test_candidate_rejects_obstacle_at_footprint_edge() -> None:
    obstacle = ((-9.5, -20.21),)
    selection = _selection(obstacles=obstacle)
    assert not selection.ok
    assert any(
        "obstacle_clearance" in candidate.reasons
        for candidate in selection.candidates
    )


def test_candidate_rejects_narrow_bay() -> None:
    narrow = ((-9.9, -21.6), (-9.1, -21.6), (-9.1, -20.7), (-9.9, -20.7))
    selection = _selection(bay=narrow, center=(-9.5, -21.15))
    assert not selection.ok
    assert any(
        "footprint_not_inside_bay" in candidate.reasons
        for candidate in selection.candidates
    )


def test_path_plan_is_safe_and_improves_final_geometry() -> None:
    current = _measure()
    plan = _plan(current)
    assert plan.ok, plan.reasons
    assert plan.min_boundary_clearance_m >= current.boundary_clearance_m - 1e-9
    assert plan.min_obstacle_clearance_m is None or plan.min_obstacle_clearance_m >= 0.20
    predicted = plan.predicted_final
    assert predicted.footprint_inside_bay
    assert predicted.boundary_clearance_m >= 0.10
    assert abs(predicted.heading_error_deg) <= 2.5
    assert predicted.distance_to_center_m <= 0.15
    for x, y, yaw in plan.simulated_poses:
        corners = PARKING_FOOTPRINT.corners(x, y, yaw)
        assert all(-14.4 <= cx <= -4.0 and -22.39 <= cy <= -19.89 for cx, cy in corners)


def test_path_plan_rejects_current_pose_with_insufficient_boundary() -> None:
    current = _measure(y=-21.45, yaw_deg=176.5)
    plan = _plan(current)
    assert not plan.ok
    assert plan.reasons


def test_phase_plans_are_bounded_and_reversible() -> None:
    current = _measure()
    selected = _selection().selected
    reverse = build_refinement_phase_plan(
        current, selected, "TERMINAL_REVERSE_ALIGN"
    )
    forward = build_refinement_phase_plan(
        current, selected, "TERMINAL_FORWARD_RETURN"
    )
    assert reverse.reverse and reverse.max_distance_m <= 1.8
    assert not forward.reverse and forward.max_distance_m <= 2.0
    assert reverse.target_heading_rad == pytest.approx(math.pi)
    assert forward.target_x == pytest.approx(selected.x)


def test_reverse_phase_improvement_and_forward_phase() -> None:
    current = _measure()
    reversed_pose = _measure(x=-9.4, y=-21.2, yaw_deg=-178.5)
    ok, reasons = refinement_phase_improved(
        "TERMINAL_REVERSE_ALIGN",
        before=current,
        after=reversed_pose,
        boundary_floor_m=0.052,
        tolerances=RefinementTolerances(),
    )
    assert ok, reasons
    final = _measure(x=-9.5, y=-21.14, yaw_deg=180.0)
    ok, reasons = refinement_phase_improved(
        "TERMINAL_FORWARD_RETURN",
        before=reversed_pose,
        after=final,
        boundary_floor_m=0.05,
        tolerances=RefinementTolerances(),
    )
    assert ok, reasons


def test_forward_phase_accepts_clearance_above_initial_floor() -> None:
    before = _measure(x=-7.689, y=-21.1282, yaw_deg=-177.4004)
    after = _measure(x=-9.4816, y=-21.1966, yaw_deg=-177.8625)
    assert before.boundary_clearance_m == pytest.approx(0.186, abs=1e-3)
    assert after.boundary_clearance_m == pytest.approx(0.161, abs=1e-3)
    ok, reasons = refinement_phase_improved(
        "TERMINAL_FORWARD_RETURN",
        before=before,
        after=after,
        boundary_floor_m=0.052,
        tolerances=RefinementTolerances(),
    )
    assert ok, reasons


def test_reverse_phase_rejects_clearance_below_floor() -> None:
    current = _measure()
    after = _measure(x=-9.5, y=-21.4, yaw_deg=-178.0)
    ok, reasons = refinement_phase_improved(
        "TERMINAL_REVERSE_ALIGN",
        before=current,
        after=after,
        boundary_floor_m=0.052,
        tolerances=RefinementTolerances(),
    )
    assert not ok
    assert "phase_boundary_clearance_below_floor" in reasons


def test_authorization_is_single_use_and_scoped() -> None:
    plan = _plan()
    authorization = _authorized(plan)
    assert authorization.permits_refinement
    assert authorization.permits_parking_completed is False
    assert authorization.permits_entry is False
    assert authorization.permits_alignment is False
    assert authorization.executes_motion is False
    assert authorization.consumed_at == NOW
    with pytest.raises(Exception):
        consume_refinement_authorization(
            authorization,
            task_id="cap07b-05",
            bay_id="bay03",
            slot_node_id="park_slot",
            entry_completion_id=ENTRY_COMPLETION_ID,
            plan_hash=plan.plan_hash,
            now=NOW,
        )


def test_authorization_rejects_wrong_plan_and_revocation() -> None:
    plan = _plan()
    authorization = _authorized(plan)
    with pytest.raises(Exception):
        consume_refinement_authorization(
            authorize_refinement(
                task_id="cap07b-05",
                bay_id="bay03",
                slot_node_id="park_slot",
                entry_completion_id=ENTRY_COMPLETION_ID,
                entry_authorization_id=ENTRY_AUTH_ID,
                start_pose=(plan.target.x, plan.target.y, plan.target.heading_rad),
                target_pose=(plan.target.x, plan.target.y, plan.target.heading_rad),
                plan_hash="0" * 64,
                now=NOW,
            ),
            task_id="cap07b-05",
            bay_id="bay03",
            slot_node_id="park_slot",
            entry_completion_id=ENTRY_COMPLETION_ID,
            plan_hash=plan.plan_hash,
            now=NOW,
        )
    revoked = revoke_refinement_authorization(authorization, "operator", now=NOW)
    with pytest.raises(Exception):
        consume_refinement_authorization(
            revoked,
            task_id="cap07b-05",
            bay_id="bay03",
            slot_node_id="park_slot",
            entry_completion_id=ENTRY_COMPLETION_ID,
            plan_hash=plan.plan_hash,
            now=NOW,
        )


def test_final_pose_ready() -> None:
    plan = _plan()
    authorization = _authorized(plan)
    final = _measure(x=-9.5, y=-21.14, yaw_deg=180.0)
    result = _verify(authorization, plan, final)
    assert result.stage == RefinementStage.READY
    assert result.ready
    assert result.reasons == ()
    assert result.to_metadata()["parking_completed"] is False


def test_final_heading_or_clearance_failure_is_not_ready() -> None:
    plan = _plan()
    authorization = _authorized(plan)
    bad_heading = _measure(x=-9.5, y=-21.14, yaw_deg=176.0)
    result = _verify(authorization, plan, bad_heading)
    assert result.stage == RefinementStage.FAILED
    assert not result.ready
    bad_clearance = _measure(x=-9.5, y=-21.40, yaw_deg=180.0)
    result = _verify(authorization, plan, bad_clearance)
    assert result.stage == RefinementStage.FAILED
    assert "boundary_clearance" in result.reasons


def test_final_collision_is_safe_stop() -> None:
    plan = _plan()
    authorization = _authorized(plan)
    final = _measure(x=-9.5, y=-21.14, yaw_deg=180.0, collision=1)
    result = _verify(authorization, plan, final, collision=1)
    assert result.stage == RefinementStage.SAFE_STOP
    assert "no_collision" in result.reasons


def test_unstable_final_is_valid_not_ready() -> None:
    plan = _plan()
    authorization = _authorized(plan)
    final = _measure(x=-9.5, y=-21.14, yaw_deg=180.0, stable=False)
    result = _verify(authorization, plan, final)
    assert result.stage == RefinementStage.VALID
    assert result.ready is False


def test_no_safe_refinement_preserves_safe_current_pose() -> None:
    current = _measure()
    result = no_safe_refinement_result(
        task_id="cap07b-05",
        bay_id="bay03",
        slot_node_id="park_slot",
        entry_completion_id=ENTRY_COMPLETION_ID,
        current=current,
        reasons=("no_candidate_passes_independent_geometry",),
        tolerances=RefinementTolerances(),
    )
    assert result.stage == RefinementStage.NO_SAFE
    assert result.to_metadata()["parking_completed"] is False
    assert result.reasons


def test_no_safe_refinement_rejects_unsafe_current_pose() -> None:
    current = _measure(x=-9.5, y=-21.45, yaw_deg=180.0)
    result = no_safe_refinement_result(
        task_id="cap07b-05",
        bay_id="bay03",
        slot_node_id="park_slot",
        entry_completion_id=ENTRY_COMPLETION_ID,
        current=current,
        reasons=("no_safe_refinement_path",),
        tolerances=RefinementTolerances(),
    )
    assert result.stage == RefinementStage.SAFE_STOP


def test_entry_completion_id_is_stable_and_evidence_bound() -> None:
    first = compute_entry_completion_id(
        entry_task_id="cap07b-04",
        entry_authorization_id=ENTRY_AUTH_ID,
        entry_route_hash="r" * 64,
        final_pose=(-9.4864, -21.2488, -176.5466),
        final_verification_stage="ENTRY_COMPLETED",
        final_boundary_clearance_m=0.052,
        final_heading_error_deg=3.4534,
    )
    second = compute_entry_completion_id(
        entry_task_id="cap07b-04",
        entry_authorization_id=ENTRY_AUTH_ID,
        entry_route_hash="r" * 64,
        final_pose=(-9.4864, -21.2488, -176.5466),
        final_verification_stage="ENTRY_COMPLETED",
        final_boundary_clearance_m=0.052,
        final_heading_error_deg=3.4534,
    )
    changed = compute_entry_completion_id(
        entry_task_id="cap07b-04",
        entry_authorization_id=ENTRY_AUTH_ID,
        entry_route_hash="r" * 64,
        final_pose=(-9.4864, -21.2488, -176.5466),
        final_verification_stage="ENTRY_COMPLETED",
        final_boundary_clearance_m=0.05,
        final_heading_error_deg=3.4534,
    )
    assert first == second
    assert first != changed
