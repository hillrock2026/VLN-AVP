"""Offline preflight tests for the runnable parking script arguments.

The CARLA import is faked so the test can run without a simulator. It does not
spawn, connect or move anything.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


class _Location:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z


class _Rotation:
    def __init__(self, pitch=0.0, yaw=0.0, roll=0.0):
        self.pitch, self.yaw, self.roll = pitch, yaw, roll


class _Transform:
    def __init__(self, location=None, rotation=None):
        self.location = location or _Location()
        self.rotation = rotation or _Rotation()


class _VehicleControl:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


@contextmanager
def _fake_carla_parking_dock():
    fake = types.ModuleType("carla")
    fake.Location = _Location
    fake.Rotation = _Rotation
    fake.Transform = _Transform
    fake.VehicleControl = _VehicleControl
    fake.Client = object
    original = sys.modules.get("carla")
    sys.modules["carla"] = fake
    try:
        spec = importlib.util.spec_from_file_location(
            "carla_parking_dock_under_test",
            REPO_ROOT / "scripts" / "carla_parking_dock.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module.carla = fake
        yield module
    finally:
        sys.modules.pop("carla_parking_dock_under_test", None)
        if original is None:
            sys.modules.pop("carla", None)
        else:
            sys.modules["carla"] = original


def _args(module):
    values = {
        "maneuver": "forward_arc",
        "staging_x": -4.0,
        "staging_y": -17.6,
        "staging_yaw_deg": -90.0,
        "spawn_z": 6.7,
        "slot_x": -9.5,
        "slot_y": -21.1,
        "slot_heading_deg": 180.0,
        "arc_radius": 3.5,
        "path_step_deg": 2.5,
        "speed_cap": 0.8,
        "position_tolerance_m": 0.25,
        "heading_tolerance_deg": 5.0,
        "final_distance_m": 0.12,
        "required_clearance_m": 0.2,
        "collision_margin_m": 0.2,
        "off_route_lateral_m": 0.6,
        "off_route_seconds": 0.5,
        "stuck_speed_mps": 0.15,
        "stuck_seconds": 5.0,
        "max_steps": 800,
        "max_sim_seconds": 60.0,
        "request_timeout": 180.0,
        "kernel_host": "/tmp/kernel_host",
        "bay_boundary_json": None,
    }
    assert set(values) == set(module._MOTION_ARGS)
    return SimpleNamespace(**values)


def test_motion_arg_names_match_the_argparse_destination() -> None:
    with _fake_carla_parking_dock() as module:
        module._validate_motion_args(_args(module))


def test_motion_preflight_catches_speed_cap_name_regression() -> None:
    with _fake_carla_parking_dock() as module:
        args = _args(module)
        del args.speed_cap
        args.speed_cap_mps = 0.8
        with pytest.raises(ValueError, match="speed_cap"):
            module._validate_motion_args(args)


def test_motion_preflight_rejects_non_positive_limits() -> None:
    with _fake_carla_parking_dock() as module:
        args = _args(module)
        args.max_steps = 0
        with pytest.raises(ValueError, match="max_steps"):
            module._validate_motion_args(args)


def test_execute_parking_loop_runs_with_fake_session_without_motion() -> None:
    with _fake_carla_parking_dock() as module:
        path = module.build_forward_right_arc(-4.0, -17.6, 3.5, final_x=-9.5)
        cumulative = module.cumulative_lengths(path)
        args = _args(module)
        args.max_steps = 1
        args.max_sim_seconds = 0.1
        args.final_distance_m = 0.12

        class _World:
            def get_snapshot(self):
                return SimpleNamespace(frame=1)

        class _Ego:
            bounding_box = SimpleNamespace(
                extent=SimpleNamespace(x=2.503, y=0.94)
            )

            def __init__(self):
                self.controls = []

            def apply_control(self, control):
                self.controls.append(control)

        class _Session:
            world = _World()

            def __init__(self):
                self.ticks = 0

            def sim_time(self):
                return 0.0

            def tick(self, n=1):
                self.ticks += n

            def brake_to_stop(self, ego, max_ticks=120):
                self.ticks += 1

        def _fake_state_of(ego, session):
            return {
                "t": 0.0,
                "x": -4.0,
                "y": -17.6,
                "z": 5.789,
                "yaw": -90.0,
                "speed": 0.0,
            }

        def _fake_safety_check(session, ego, points, cumulative, s, **kwargs):
            details = kwargs.get("details_out")
            if details is not None:
                details.update(
                    {
                        "verdict": {
                            "blocked": False,
                            "obstacle_hit": False,
                            "ground_bad": False,
                            "stop_distance_m": 3.0,
                            "min_hit_m": None,
                            "ground_z": [5.8, 5.8, 5.8],
                        },
                        "rays": [],
                        "ground_probes": [],
                        "ground_probe_inside_ego": False,
                    }
                )
            return False, None, [5.8, 5.8, 5.8]

        module.nav01b.state_of = _fake_state_of
        module.nav01b.safety_check = _fake_safety_check
        result = module._execute_parking(
            session=_Session(),
            ego=_Ego(),
            path=path,
            cumulative=cumulative,
            args=args,
            collision_events=[],
            collision_lock=__import__("threading").Lock(),
            run_id="unit-test",
            obstacles=[],
            collision_margin_m=0.2,
        )
        assert result["status"] == "stopped"
        assert result["stop_reason"] == "max_steps"
        assert result["steps"] == 1
        assert result["motion_executed"] is False
        assert len(result["records"]) == 1
        assert result["records"][0]["control"]["reverse"] is False


def test_execute_parking_reverse_branch_uses_reverse_control() -> None:
    with _fake_carla_parking_dock() as module:
        path = ((-4.0, -21.14), (-9.5, -21.14))
        cumulative = module.cumulative_lengths(path)
        args = _args(module)
        args.maneuver = "reverse_straight"
        args.staging_y = -21.14
        args.staging_yaw_deg = 0.0
        args.slot_y = -21.14
        args.slot_heading_deg = 0.0
        args.max_steps = 1

        class _World:
            def get_snapshot(self):
                return SimpleNamespace(frame=1)

        class _Ego:
            bounding_box = SimpleNamespace(
                extent=SimpleNamespace(x=2.503, y=0.94)
            )

            def __init__(self):
                self.controls = []

            def apply_control(self, control):
                self.controls.append(control)

        class _Session:
            world = _World()

            def sim_time(self):
                return 0.0

            def tick(self, n=1):
                pass

            def brake_to_stop(self, ego, max_ticks=120):
                pass

        def _fake_state_of(ego, session):
            return {
                "t": 0.0,
                "x": -4.0,
                "y": -21.14,
                "z": 5.79,
                "yaw": 0.0,
                "speed": 0.0,
            }

        def _fake_safety_check(session, ego, points, cumulative, s, **kwargs):
            details = kwargs.get("details_out")
            if details is not None:
                details.update(
                    {
                        "verdict": {
                            "blocked": False,
                            "obstacle_hit": False,
                            "ground_bad": False,
                            "stop_distance_m": 3.0,
                            "min_hit_m": None,
                            "ground_z": [5.8, 5.8, 5.8],
                        },
                        "rays": [],
                        "ground_probes": [],
                        "ground_probe_inside_ego": False,
                        "reverse": True,
                        "probe_origin": "rear",
                    }
                )
            return False, None, [5.8, 5.8, 5.8]

        module.nav01b.state_of = _fake_state_of
        module.nav01b.safety_check = _fake_safety_check
        result = module._execute_parking(
            session=_Session(),
            ego=_Ego(),
            path=path,
            cumulative=cumulative,
            args=args,
            collision_events=[],
            collision_lock=__import__("threading").Lock(),
            run_id="unit-test-reverse",
            obstacles=[],
            collision_margin_m=0.2,
        )
        assert result["stop_reason"] == "max_steps"
        assert result["motion_executed"] is False
        assert len(result["records"]) == 1
        assert result["records"][0]["control"]["reverse"] is True
        assert result["records"][0]["safety"]["probe_origin"] == "rear"
