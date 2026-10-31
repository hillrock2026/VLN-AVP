"""Integration test for the per-tick terminal boundary floor guard.

The real ``_drive_terminal_phase`` loop is driven with a fake CARLA session
and ego: no server, no world settings change and no real vehicle motion. The
fake ego records every control command, so the test can prove that a guard
trigger stops the loop before any further throttle is applied.

Run directly in the CARLA venv (pytest is not installed there):

    /home/gaosong/workspace/.venv-carla010/bin/python -m unittest \
        tests.vln.test_entry_terminal_floor_guard_drive -v

The default pytest environment skips the class because the CARLA Python API is
not installed there.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT / "src", REPO_ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

try:
    import carla  # type: ignore

    import carla_cap07b04_entry as entry04  # type: ignore
    from vln.carla.entry_scene import bay03_entry_route  # type: ignore
    from vln.carla.entry_terminal import (  # type: ignore
        TerminalCorrectionConfig,
        TerminalPhase,
        terminal_phase_plan,
    )
    from vln.parking.entry import (  # type: ignore
        EntryBudget,
        EntryStability,
        measure_entry,
    )

    CARLA_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on the interpreter
    CARLA_AVAILABLE = False


START = (-3.9959, -17.1843, math.radians(-89.5386))


class _Snapshot:
    def __init__(self, frame: int) -> None:
        self.frame = frame


class _World:
    def __init__(self) -> None:
        self.frame = 1000

    def get_snapshot(self) -> _Snapshot:
        return _Snapshot(self.frame)


class _FakeSession:
    """Minimal Session surface used by the terminal loop and safety_check."""

    def __init__(self) -> None:
        self.world = _World()
        self._time = 0.0
        self.ticks = 0

    def tick(self, n: int = 1) -> None:
        self.ticks += n
        self.world.frame += n
        self._time += 0.05 * n

    def sim_time(self) -> float:
        return self._time

    def ray(self, start, end):
        return None

    def floor_at(self, x, y, z=7.0):
        return 5.8


class _FakeEgo:
    def __init__(
        self,
        x: float,
        y: float,
        yaw_deg: float,
        *,
        bounding_box_error: bool = False,
    ) -> None:
        self._transform = carla.Transform(
            carla.Location(x=x, y=y, z=5.7859),
            carla.Rotation(yaw=yaw_deg),
        )
        self._bounding_box = SimpleNamespace(
            extent=carla.Vector3D(2.503, 0.9405, 0.7702),
            location=carla.Location(0.0, 0.0, 0.0),
        )
        self._bounding_box_error = bounding_box_error
        self.controls = []

    @property
    def bounding_box(self):
        if self._bounding_box_error:
            raise RuntimeError("bounding box unavailable")
        return self._bounding_box

    def get_transform(self):
        return self._transform

    def get_velocity(self):
        return carla.Vector3D(0.0, 0.0, 0.0)

    def apply_control(self, control) -> None:
        self.controls.append(control)


@unittest.skipUnless(CARLA_AVAILABLE, "CARLA python API is not available")
class TerminalFloorGuardDriveTests(unittest.TestCase):
    def _route(self):
        route, _audit = bay03_entry_route(
            task_id="cap07b-06-guard-test",
            actual_pose=START,
            obstacle_points=(),
        )
        return route

    def _measurement(self, route, x, y, yaw_deg):
        return measure_entry(
            route,
            x=x,
            y=y,
            yaw_rad=math.radians(yaw_deg),
            speed_mps=0.0,
            stopped=True,
            route_s=route.length_m,
            cross_track_m=0.0,
            stability=EntryStability(3, 0.0, 0.0, True),
            collision_count=0,
        )

    def _run(self, *, x, y, yaw_deg, floor, bounding_box_error=False):
        route = self._route()
        measurement = self._measurement(route, x, y, yaw_deg)
        plan = terminal_phase_plan(
            route, measurement, TerminalPhase.FORWARD_RETURN
        )
        session = _FakeSession()
        ego = _FakeEgo(
            x,
            y,
            yaw_deg,
            bounding_box_error=bounding_box_error,
        )
        result = entry04._drive_terminal_phase(
            session,
            ego,
            route,
            plan,
            config=TerminalCorrectionConfig(),
            budget=EntryBudget(),
            baseline_collisions=0,
            collision_events=[],
            min_boundary_clearance=floor,
        )
        return result, ego

    def test_floor_below_current_clearance_stops_before_any_motion(self) -> None:
        result, ego = self._run(
            x=-9.4816, y=-21.35, yaw_deg=-177.8625, floor=0.15
        )
        self.assertTrue(result["boundary_floor"]["enabled"])
        self.assertTrue(result["boundary_floor"]["triggered"])
        self.assertEqual(result["stop_reason"], "boundary_below_floor")
        self.assertTrue(result["safety_stop"])
        self.assertFalse(result["phase_success"])
        trigger = result["records"][-1]["boundary_floor_trigger"]
        self.assertEqual(trigger["reason"], "boundary_below_floor")
        self.assertEqual(trigger["frame"], 1000)
        self.assertTrue(trigger["transform"])
        self.assertTrue(trigger["bounding_box"])
        # Only the final brake command is applied; no throttle ever reached
        # the ego, so the caller cannot execute a subsequent segment.
        self.assertTrue(ego.controls)
        self.assertTrue(all(control.throttle == 0.0 for control in ego.controls))
        self.assertTrue(all(control.brake == 1.0 for control in ego.controls))

    def test_floor_above_current_clearance_passes_and_records_state(self) -> None:
        result, ego = self._run(
            x=-9.4816, y=-21.1966, yaw_deg=-177.8625, floor=0.05
        )
        self.assertFalse(result["boundary_floor"]["triggered"])
        self.assertGreater(result["boundary_floor"]["min_clearance_m"], 0.15)
        self.assertIn(result["stop_reason"], ("slot_aligned", "slot_x_reached"))
        self.assertTrue(result["phase_success"])
        self.assertTrue(ego.controls)
        self.assertTrue(all(control.throttle == 0.0 for control in ego.controls))

    def test_unreadable_bounding_box_fails_closed(self) -> None:
        result, ego = self._run(
            x=-9.4816,
            y=-21.1966,
            yaw_deg=-177.8625,
            floor=0.05,
            bounding_box_error=True,
        )
        self.assertEqual(result["stop_reason"], "boundary_state_unreadable")
        self.assertTrue(result["safety_stop"])
        self.assertFalse(result["phase_success"])
        self.assertIn("bounding box unavailable", result["records"][-1]["boundary_floor_trigger"]["error"])
        self.assertTrue(all(control.throttle == 0.0 for control in ego.controls))


if __name__ == "__main__":
    unittest.main()
