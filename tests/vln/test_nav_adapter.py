"""Offline tests for the decision -> ``AgentIntent`` v1 mapping layer.

No model, no network, no image and no host: the subject is the arithmetic and the
refusals of the one place where a discrete visual direction becomes numbers.

Module under test: :mod:`vln.nav.adapter`.
"""

from __future__ import annotations

import math

import pytest

from vln.intent.agent_intent import (
    ACTION_PARKING_MOVE,
    CONTRACT_VERSION,
    REQUIRED_FIELDS,
    REQUIRED_TARGET_FIELDS,
    AgentIntent,
    AgentIntentValidationError,
    normalize_heading,
)
from vln.intent.model_output import parse_model_output
from vln.nav import (
    DIRECTION_HEADING_DELTA,
    NavigationDirective,
    NavigationMappingError,
    VehiclePose,
    parse_visual_decision,
    to_agent_intent,
    verify_visual_decision,
)
from vln.vlm.nav_prompt import DIRECTION_ANSWERS, Variant, build_nav_prompt

_POSE = VehiclePose(x=1.0, y=-2.0, heading=0.0)


def _directive(direction: str, position: str | None = None) -> NavigationDirective:
    """A verified directive for ``direction``, built through the real layers."""

    mapping = {"LEFT": "LEFT", "RIGHT": "RIGHT", "STRAIGHT": "AHEAD"}
    position = position or mapping[direction]
    raw = (
        "Target: D50\n"
        "Identified as: D50\n"
        "Visible: 是\n"
        f"Relative position: {position}\n"
        f"Next direction: {direction}\n"
        "Evidence: 地面白色编号\n"
    )
    return verify_visual_decision(
        parse_visual_decision(raw), expected_identity="D50"
    )


# ----------------------------------------------------------------------
# The mapping contract
# ----------------------------------------------------------------------


def test_the_delta_table_covers_exactly_the_prompt_directions() -> None:
    """No approved direction may be unmappable, and no extra one may appear."""

    assert set(DIRECTION_HEADING_DELTA) == set(DIRECTION_ANSWERS[:-1])
    assert DIRECTION_ANSWERS[-1] not in DIRECTION_HEADING_DELTA


def test_the_delta_table_is_read_only() -> None:
    with pytest.raises(TypeError):
        DIRECTION_HEADING_DELTA["UP"] = 0.0  # type: ignore[index]


def test_the_delta_signs_follow_the_frozen_counter_clockwise_heading_convention() -> None:
    assert DIRECTION_HEADING_DELTA["LEFT"] > 0  # counter-clockwise
    assert DIRECTION_HEADING_DELTA["RIGHT"] < 0
    assert DIRECTION_HEADING_DELTA["STRAIGHT"] == 0.0
    assert DIRECTION_HEADING_DELTA["LEFT"] == -DIRECTION_HEADING_DELTA["RIGHT"]


@pytest.mark.parametrize("direction", sorted(DIRECTION_HEADING_DELTA))
@pytest.mark.parametrize("pose_heading", [0.0, 0.25, -3.0, math.pi - 0.01, 3.0])
def test_the_target_heading_is_the_pose_heading_plus_the_delta(
    direction: str, pose_heading: float
) -> None:
    pose = VehiclePose(x=4.0, y=5.0, heading=pose_heading)
    intent = to_agent_intent(_directive(direction), pose=pose, intent_id="nav-09")
    assert intent.target.heading == normalize_heading(
        pose.heading + DIRECTION_HEADING_DELTA[direction]
    )


def test_the_heading_wraps_instead_of_leaving_the_normalized_range() -> None:
    """A left turn from just under +pi lands just past -pi/2, i.e. inside range."""

    pose = VehiclePose(x=0.0, y=0.0, heading=math.pi - 0.1)
    intent = to_agent_intent(_directive("LEFT"), pose=pose, intent_id="nav-09")
    assert -math.pi <= intent.target.heading < math.pi
    assert intent.target.heading == pytest.approx(-math.pi / 2 - 0.1, abs=1e-9)


def test_the_target_position_is_the_pose_position_because_none_is_computed() -> None:
    """The documented placeholder: no displacement is derived from a direction."""

    pose = VehiclePose(x=-7.25, y=3.5, heading=1.0)
    intent = to_agent_intent(_directive("RIGHT"), pose=pose, intent_id="nav-09")
    assert (intent.target.x, intent.target.y) == (-7.25, 3.5)


@pytest.mark.parametrize("direction", sorted(DIRECTION_HEADING_DELTA))
def test_only_the_heading_depends_on_the_direction(direction: str) -> None:
    intent = to_agent_intent(_directive(direction), pose=_POSE, intent_id="nav-09")
    assert (intent.target.x, intent.target.y) == (_POSE.x, _POSE.y)


def test_the_bare_straight_direction_leaves_the_heading_unchanged() -> None:
    pose = VehiclePose(x=0.0, y=0.0, heading=0.75)
    intent = to_agent_intent(_directive("STRAIGHT"), pose=pose, intent_id="nav-09")
    assert intent.target.heading == pose.heading


def test_the_intent_carries_the_frozen_v1_identity_fields() -> None:
    intent = to_agent_intent(_directive("LEFT"), pose=_POSE, intent_id="nav-09-intent")
    assert intent.intent_id == "nav-09-intent"
    assert intent.contract_version == CONTRACT_VERSION
    assert intent.action == ACTION_PARKING_MOVE


def test_the_result_is_an_agent_intent_of_the_existing_schema() -> None:
    """No new field, no renamed field: exactly the frozen v1 key sets."""

    intent = to_agent_intent(_directive("LEFT"), pose=_POSE, intent_id="nav-09")
    assert isinstance(intent, AgentIntent)
    obj = intent.to_object()
    assert set(obj) == set(REQUIRED_FIELDS)
    assert set(obj["target"]) == set(REQUIRED_TARGET_FIELDS)


def test_the_payload_is_accepted_by_the_existing_v1_parsers() -> None:
    """The mapped intent round-trips through the authoritative v1 entry points."""

    intent = to_agent_intent(_directive("RIGHT"), pose=_POSE, intent_id="nav-09")
    payload = intent.to_payload()
    assert AgentIntent.from_payload(payload) == intent
    assert parse_model_output(payload) == intent


def test_the_mapping_is_deterministic() -> None:
    first = to_agent_intent(_directive("LEFT"), pose=_POSE, intent_id="nav-09")
    second = to_agent_intent(_directive("LEFT"), pose=_POSE, intent_id="nav-09")
    assert first.to_payload() == second.to_payload()


# ----------------------------------------------------------------------
# Refusals - the layer guesses nothing
# ----------------------------------------------------------------------


@pytest.mark.parametrize("pose", [None, 1.0, "pose", (1.0, 2.0, 0.0), {"x": 1.0}])
def test_a_missing_or_wrong_pose_is_refused(pose: object) -> None:
    with pytest.raises(NavigationMappingError, match="VehiclePose"):
        to_agent_intent(_directive("LEFT"), pose=pose, intent_id="nav-09")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "directive",
    [
        "Target: D50\nVisible: 是\n",  # raw model text
        None,
        "LEFT",
        {"direction": "LEFT"},
    ],
)
def test_raw_or_unverified_input_cannot_reach_an_intent(directive: object) -> None:
    """Only a verified directive may be mapped - the type is the guarantee."""

    with pytest.raises(NavigationMappingError, match="NavigationDirective"):
        to_agent_intent(directive, pose=_POSE, intent_id="nav-09")  # type: ignore[arg-type]


def test_a_parsed_but_unverified_decision_is_not_accepted() -> None:
    decision = parse_visual_decision(
        "Target: D50\nIdentified as: D50\nVisible: 是\n"
        "Relative position: LEFT\nNext direction: LEFT\nEvidence: x\n"
    )
    with pytest.raises(NavigationMappingError):
        to_agent_intent(decision, pose=_POSE, intent_id="nav-09")  # type: ignore[arg-type]


@pytest.mark.parametrize("direction", ["UP", "FORWARD", "", "left"])
def test_a_direction_with_no_declared_delta_is_refused(direction: str) -> None:
    """A hand-built directive must not smuggle in an undeclared direction."""

    rogue = NavigationDirective(
        direction=direction, position="LEFT", identified_as="D50", evidence="x"
    )
    with pytest.raises(NavigationMappingError, match="no declared heading delta"):
        to_agent_intent(rogue, pose=_POSE, intent_id="nav-09")


@pytest.mark.parametrize("pose", [VehiclePose(x=0, y=0, heading=0)], ids=["ints-ok"])
def test_integer_pose_values_are_accepted(pose: VehiclePose) -> None:
    intent = to_agent_intent(_directive("LEFT"), pose=pose, intent_id="nav-09")
    assert intent.target.x == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"x": True, "y": 0.0, "heading": 0.0},
        {"x": "1.0", "y": 0.0, "heading": 0.0},
        {"x": 0.0, "y": None, "heading": 0.0},
        {"x": 0.0, "y": 0.0, "heading": math.nan},
        {"x": 0.0, "y": 0.0, "heading": math.inf},
    ],
)
def test_an_invalid_pose_value_is_refused(kwargs: dict) -> None:
    with pytest.raises(NavigationMappingError):
        VehiclePose(**kwargs)


def test_a_pose_heading_is_stored_normalized() -> None:
    """The v1 range is half-open ``[-pi, pi)``, so ``+pi`` is stored as ``-pi``."""

    assert VehiclePose(x=0.0, y=0.0, heading=3.0 * math.pi).heading == pytest.approx(
        -math.pi, abs=1e-9
    )
    assert VehiclePose(x=0.0, y=0.0, heading=0.5).heading == 0.5


def test_an_invalid_intent_id_surfaces_as_the_authoritative_v1_error() -> None:
    """The layer does not restate the v1 rule: the contract's own error appears."""

    for bad in ("", "   ", 7, None):
        with pytest.raises(AgentIntentValidationError) as excinfo:
            to_agent_intent(_directive("LEFT"), pose=_POSE, intent_id=bad)  # type: ignore[arg-type]
        assert not isinstance(excinfo.value, NavigationMappingError)


def test_the_mapping_never_produces_an_all_zero_target() -> None:
    """06A's degenerate ``(0,0,0)`` must come only from a genuine zero pose."""

    intent = to_agent_intent(
        _directive("LEFT"), pose=VehiclePose(x=2.0, y=-1.0, heading=0.0), intent_id="n"
    )
    assert (intent.target.x, intent.target.y, intent.target.heading) != (0.0, 0.0, 0.0)


def test_the_layer_does_not_submit_anything() -> None:
    """The mapping output is a value; no host, request or response is involved."""

    intent = to_agent_intent(_directive("LEFT"), pose=_POSE, intent_id="nav-09")
    assert set(intent.__dataclass_fields__) == {
        "intent_id",
        "target",
        "contract_version",
        "action",
    }
    assert not hasattr(intent, "send")


def test_the_prompt_the_parser_expects_is_the_08a_prompt() -> None:
    """A guard against the prompt drifting away from the parser silently."""

    text = build_nav_prompt(
        Variant.TARGET_DIRECTION, target="D50", require_identity=True
    )
    assert "Identified as:" in text
