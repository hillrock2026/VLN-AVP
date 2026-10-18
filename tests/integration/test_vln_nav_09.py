"""09 integration: model response -> visual judgement -> ``AgentIntent`` v1.

Two groups:

* **Mock-driven (always runs, no network).** The existing
  :class:`~vln.vlm.MockModelClient` supplies the raw text, so every branch of the
  chain is exercised deterministically - a legal judgement, a wrong identity, a
  missing direction, malformed text, a model failure - and the chain is shown to
  stop at the right layer each time. A spy host factory and a spy request builder
  are wired in and must stay at **zero calls** for both successes and failures:
  the layer that turns a judgement into an intent returns a validated value and
  never enters the execution path.
* **Real-model smoke (gated on ``VLN_ZDTAICHU_NAV_09=1``).** The real
  ``ZDTaichu5.0-9B`` service on ``127.0.0.1:8100`` judges native, unmagnified
  frames and the chain runs on its actual output.

What this file does NOT prove, and must not be read as proving: that the mapping
is vehicle kinematics (it is a declared simulation convention - see
:mod:`vln.nav.adapter`), that a vehicle moved, that bay numbers are readable, or
that a RIGHT upright positive exists. 08A found no upright bay number and no
well-posed upright RIGHT target in the available frames, so the only real
positives used here are the ones 08A certified.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_vln_nav_07b import _install_recorder, server_client_module  # noqa: E402

from vln.intent.agent_intent import AgentIntent, AgentIntentValidationError  # noqa: E402
from vln.intent.model_output import parse_model_output  # noqa: E402
from vln.nav import (  # noqa: E402
    EvidenceInsufficientError,
    NavigationDirective,
    NavigationMappingError,
    TargetIdentityMismatchError,
    TargetNotVisibleError,
    VehiclePose,
    VisualDecisionParseError,
    VisualDecisionValidationError,
    VisualNavigationDecision,
    parse_visual_decision,
    to_agent_intent,
    verify_visual_decision,
)
from vln.vlm import MockModelClient, ModelCallError  # noqa: E402
from vln.vlm.image_input import load_image_part  # noqa: E402
from vln.vlm.nav_prompt import Variant, build_nav_prompt  # noqa: E402
from vln.vlm.server_client import ZDTaichuServerBackend  # noqa: E402
from vln.vlm.zdtaichu_client import PreparedObservation  # noqa: E402

pytestmark = pytest.mark.integration

_IMAGES_DIR = Path(__file__).resolve().parents[2] / "images"
_SMOKE_ENV = "VLN_ZDTAICHU_NAV_09"
_OUT_ENV = "VLN_ZDTAICHU_NAV_09_OUT"

_IMG01 = "17931c01d3fda4038c76944a334b3aef.png"
_IMG04 = "9a6908511ef1211af2ae8483c103bb63.png"

#: An arbitrary, labelled placeholder pose for the real-model smoke test. This
#: project has no localisation, odometry or simulator, so no pose can be
#: *measured* here; the layer requires one explicitly rather than inventing it,
#: and the value below is only a carrier for the heading delta. It is not a
#: measurement and not a vehicle state.
_SMOKE_POSE = VehiclePose(x=12.5, y=-4.0, heading=0.25)

_BLOCK_TEMPLATE = (
    "第五步 输出结论块：\n"
    "Target: {target}\n"
    "Identified as: {identified}\n"
    "Visible: {visible}\n"
    "Relative position: {position}\n"
    "Next direction: {direction}\n"
    "Evidence: {evidence}\n"
)


def _block(
    *,
    target: str = "D50",
    identified: str = "D50",
    visible: str = "是",
    position: str = "LEFT",
    direction: str = "LEFT",
    evidence: str = "地面白色编号 D50",
) -> str:
    return _BLOCK_TEMPLATE.format(
        target=target,
        identified=identified,
        visible=visible,
        position=position,
        direction=direction,
        evidence=evidence,
    )


class _HostSpy:
    """A counted stand-in for the NAV-10 execution step.

    It plays the part the host client and the IPC request builder will play once
    NAV-10 wires this layer up, so the *ordering* is testable: nothing may be
    built or submitted unless all three layers succeeded. On every failure path
    the three counters must stay at zero; on the success path they must be exactly
    one each. No real host, Kernel or executor is involved - ``send`` returns a
    sentinel, not a ``Response``.
    """

    def __init__(self) -> None:
        self.builds = 0
        self.request_builds = 0
        self.sent: list = []

    def host_client_factory(self) -> "_HostSpy":
        self.builds += 1
        return self

    def request_builder(self, intent: AgentIntent, *, request_id: str) -> tuple:
        self.request_builds += 1
        return (request_id, intent.to_payload())

    def __enter__(self) -> "_HostSpy":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def send(self, request: tuple) -> str:
        self.sent.append(request)
        return "sentinel-response"

    def assert_untouched(self) -> None:
        assert self.builds == 0, "a host client was constructed"
        assert self.request_builds == 0, "an IPC request was built"
        assert self.sent == [], "something was submitted"

    def assert_submitted_once(self, intent: AgentIntent) -> None:
        assert (self.builds, self.request_builds, len(self.sent)) == (1, 1, 1)
        assert self.sent[0][1] == intent.to_payload()


def _run_chain(
    *,
    model,
    instruction: str,
    expected_identity: str,
    spy: _HostSpy,
    observation: object = "a parking-lot frame",
    pose: VehiclePose = _SMOKE_POSE,
    intent_id: str = "nav-09-intent",
) -> AgentIntent:
    """The intended NAV-09/NAV-10 order: generate -> 3 layers -> execute.

    Written out rather than hidden behind one helper in ``src``: the layering is
    the deliverable, and ``to_agent_intent`` already refuses anything that is not
    a verified :class:`NavigationDirective`, so no caller can skip a step. The
    two lines after the layers are the *future* NAV-10 execution step, kept here
    so a failure can be shown never to reach it.
    """

    raw = model.generate(observation, instruction)
    decision = parse_visual_decision(raw)
    directive = verify_visual_decision(decision, expected_identity=expected_identity)
    intent = to_agent_intent(directive, pose=pose, intent_id=intent_id)

    request = spy.request_builder(intent, request_id="nav-09-req-1")
    with spy.host_client_factory() as client:
        client.send(request)
    return intent


# ----------------------------------------------------------------------
# The happy path
# ----------------------------------------------------------------------


def test_a_matching_judgement_becomes_a_validated_agent_intent() -> None:
    spy = _HostSpy()
    model = MockModelClient(_block())

    intent = _run_chain(
        model=model,
        instruction="park at D50",
        expected_identity="D50",
        spy=spy,
    )

    assert isinstance(intent, AgentIntent)
    assert model.call_count == 1
    # Reached only because every layer succeeded; the submission carries this
    # intent's own payload and nothing else.
    spy.assert_submitted_once(intent)


def test_the_produced_intent_is_the_existing_v1_wire_format() -> None:
    spy = _HostSpy()
    model = MockModelClient(_block(position="AHEAD", direction="STRAIGHT"))
    intent = _run_chain(
        model=model,
        instruction="find the exit",
        expected_identity="D50",
        spy=spy,
    )

    assert set(intent.to_object()) == {
        "contract_version",
        "intent_id",
        "action",
        "target",
    }
    assert set(intent.to_object()["target"]) == {"x", "y", "heading"}
    # The produced payload is accepted by the pre-existing model-output gate.
    assert parse_model_output(intent.to_payload()) == intent


def test_each_direction_reaches_its_own_target_heading() -> None:
    cases = {"LEFT": "LEFT", "RIGHT": "RIGHT", "STRAIGHT": "AHEAD"}
    for direction, position in cases.items():
        spy = _HostSpy()
        intent = _run_chain(
            model=MockModelClient(_block(position=position, direction=direction)),
            instruction="park at D50",
            expected_identity="D50",
            spy=spy,
        )
        assert intent.target.heading != 0.0 or direction == "STRAIGHT"
        assert (intent.target.x, intent.target.y) == (_SMOKE_POSE.x, _SMOKE_POSE.y)


def test_a_judgement_is_a_directive_before_it_is_an_intent() -> None:
    """Visual success and intent success are separate, observable levels."""

    decision = parse_visual_decision(_block())
    assert isinstance(decision, VisualNavigationDecision)
    directive = verify_visual_decision(decision, expected_identity="D50")
    assert isinstance(directive, NavigationDirective)
    assert not isinstance(directive, AgentIntent)
    intent = to_agent_intent(directive, pose=_SMOKE_POSE, intent_id="nav-09")
    assert isinstance(intent, AgentIntent)


# ----------------------------------------------------------------------
# Failure paths - each must refuse, and none may reach the execution path
# ----------------------------------------------------------------------


def _assert_refused_and_inert(
    model, *, expected_identity: str, error: type, pose: VehiclePose = _SMOKE_POSE
) -> None:
    """A refusal must propagate before the execution step is reached."""

    spy = _HostSpy()
    with pytest.raises(error):
        _run_chain(
            model=model,
            instruction="x",
            expected_identity=expected_identity,
            spy=spy,
            pose=pose,
        )
    spy.assert_untouched()


@pytest.mark.parametrize(
    "raw,error",
    [
        # layer 1: structure
        ("", VisualDecisionParseError),
        ("I could not decide.", VisualDecisionParseError),
        (_block().replace("Next direction: LEFT\n", ""), VisualDecisionParseError),
        (_block() + _block(), VisualDecisionParseError),
        ("Target: D50\nIdentified as: D50\nVisible: 是\n"
         "Relative position: LEFT\nNext direction: \nEvidence: x\n",
         VisualDecisionParseError),
        # layer 2: executability
        (_block(visible="否", position="无法确定", direction="无法确定"), TargetNotVisibleError),
        (_block(identified="050"), TargetIdentityMismatchError),
        (_block(identified="无法确定"), TargetIdentityMismatchError),
        (_block(direction="无法确定"), VisualDecisionValidationError),
        (_block(position="右侧", direction="RIGHT"), VisualDecisionValidationError),
        (_block(position="AHEAD", direction="RIGHT"), VisualDecisionValidationError),
        (_block(evidence="无法确定"), EvidenceInsufficientError),
        (_block(evidence="证据不足，无法确定"), EvidenceInsufficientError),
        (_block(visible="no", position="无法确定", direction="无法确定"),
         VisualDecisionValidationError),
    ],
)
def test_a_bad_judgement_never_becomes_an_intent(raw: str, error: type) -> None:
    _assert_refused_and_inert(
        MockModelClient(raw), expected_identity="D50", error=error
    )


def test_a_mismatched_identity_is_refused_even_though_the_block_is_well_formed() -> None:
    """The 08A anchoring case: `identified_as` is checked, never trusted."""

    model = MockModelClient(
        _block(target="316", identified="316", position="RIGHT", direction="RIGHT")
    )
    _assert_refused_and_inert(
        model,
        expected_identity="283",
        error=TargetIdentityMismatchError,
    )


def test_a_model_failure_is_not_converted_into_a_judgement() -> None:
    class _FailingModel:
        def generate(self, observation: object, instruction: str) -> str:
            raise ModelCallError("the service refused the request")

    spy = _HostSpy()
    with pytest.raises(ModelCallError):
        _run_chain(
            model=_FailingModel(),
            instruction="x",
            expected_identity="D50",
            spy=spy,
        )
    spy.assert_untouched()


def test_a_visual_success_that_cannot_be_mapped_is_refused_at_the_mapping_layer() -> None:
    """Three distinguishable outcomes: judgement OK, mapping impossible."""

    decision = parse_visual_decision(_block())
    directive = verify_visual_decision(decision, expected_identity="D50")
    assert isinstance(directive, NavigationDirective)
    with pytest.raises(NavigationMappingError):
        to_agent_intent(directive, pose=None, intent_id="nav-09")  # type: ignore[arg-type]
    # ...and through the full chain, still nothing is submitted.
    _assert_refused_and_inert(
        MockModelClient(_block()),
        expected_identity="D50",
        error=NavigationMappingError,
        pose=None,  # type: ignore[arg-type]
    )


def test_a_contract_violation_still_surfaces_as_the_v1_error() -> None:
    """The layer does not shadow the authoritative contract error."""

    spy = _HostSpy()
    with pytest.raises(AgentIntentValidationError):
        _run_chain(
            model=MockModelClient(_block()),
            instruction="park at D50",
            expected_identity="D50",
            spy=spy,
            intent_id="   ",
        )
    spy.assert_untouched()


def test_nothing_in_the_chain_imports_the_execution_path() -> None:
    """Structural backstop for the spy above: no client, no orchestrator.

    The nav modules must not name the host client, the orchestrator, the IPC
    bridge or a process spawner anywhere in their source - so no future edit can
    quietly give the layer an execution path to reach.
    """

    import inspect

    import vln.nav
    import vln.nav.adapter
    import vln.nav.errors
    import vln.nav.visual_decision

    forbidden = ("HostClient", "run_parking_intent", "subprocess", "build_request", "run_parking_loop")
    for module in (
        vln.nav,
        vln.nav.adapter,
        vln.nav.errors,
        vln.nav.visual_decision,
    ):
        source = inspect.getsource(module)
        for name in forbidden:
            assert name not in source, f"{module.__name__} mentions {name}"


# ----------------------------------------------------------------------
# Replay of the recorded 08A model outputs (offline, real model evidence)
# ----------------------------------------------------------------------

#: Every round 08A recorded, replayed through the 09 chain offline. The outcomes
#: are what the recorded real model output produces, so this is a regression
#: guard on real evidence rather than on synthetic text.
_REPLAY_OUTCOMES = {
    "U-EXIT-LEFT": ("intent", "LEFT"),
    "U-EXIT-AHEAD": ("intent", "STRAIGHT"),
    "U-ZONE-A": ("intent", "RIGHT"),
    "U-ZONE-C": ("parse-refused", None),
    "B-D50": ("not-visible", None),
    "B-316": ("intent", "RIGHT"),
    "N-P07-IMG01": ("not-visible", None),
    "N-P07-IMG03": ("not-visible", None),
    "N-ZONE-A-IMG01": ("not-visible", None),
    "X-283-IMG04": ("intent", "LEFT"),
    "X-D50-ABSENT-IMG04": ("not-visible", None),
    "X-999-ABSENT-IMG04": ("not-visible", None),
}


def _replay(raw: str, target: str) -> tuple:
    """Classify one recorded answer the way the 09 chain does."""

    try:
        decision = parse_visual_decision(raw)
    except VisualDecisionParseError:
        return "parse-refused", None
    try:
        directive = verify_visual_decision(decision, expected_identity=target)
    except TargetNotVisibleError:
        return "not-visible", None
    except VisualDecisionValidationError:
        return "verify-refused", None
    intent = to_agent_intent(directive, pose=_SMOKE_POSE, intent_id=f"replay-{target}")
    assert parse_model_output(intent.to_payload()) == intent
    return "intent", directive.direction


def _load_08a_rounds() -> dict:
    """The 08A per-round records, keyed by scene id.

    Only the per-round records carry a single ``raw`` answer; the repeat and
    summary records are skipped (their ``scored`` is a list, not an object).
    """

    raw_file = Path(__file__).resolve().parents[2] / "docs" / "M1-VLN-NAV-08A-RAW.jsonl"
    assert raw_file.is_file(), f"the 08A evidence file is missing: {raw_file}"
    rounds = {}
    for line in raw_file.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if isinstance(record.get("scored"), dict) and "raw" in record:
            rounds[record["scene_id"]] = record
    return rounds


def test_replaying_the_recorded_08a_outputs_gives_the_recorded_classification() -> None:
    records = _load_08a_rounds()
    observed = {
        scene_id: _replay(record["raw"], record["target"])
        for scene_id, record in records.items()
    }
    assert observed == _REPLAY_OUTCOMES

    tally: dict = {}
    for outcome, _ in observed.values():
        tally[outcome] = tally.get(outcome, 0) + 1
    assert tally == {"intent": 5, "not-visible": 6, "parse-refused": 1}


def test_the_chain_still_admits_the_two_anchored_claims_it_cannot_detect() -> None:
    """A documented limitation, asserted so it cannot quietly be believed fixed.

    08A showed (target-free read of the same frames) that the model's ``316`` and
    ``283`` identities are prompt-anchored, not reads. Both still pass this chain:
    the declared identity matches the request, and no in-band check can tell a
    declared identity from a read one. Only 08A's target-free control can, which
    is why a named-target positive must never be trusted without it.
    """

    records = _load_08a_rounds()
    for scene_id, target in (("B-316", "316"), ("X-283-IMG04", "283")):
        outcome, direction = _replay(records[scene_id]["raw"], target)
        assert outcome == "intent", scene_id
        assert direction in ("LEFT", "RIGHT")


# ----------------------------------------------------------------------
# Real-model smoke (gated)
# ----------------------------------------------------------------------

#: 08A-certified positives only: the two upright 出口/EXIT signs, plus hidden and
#: no-image controls. The rotated deck numbers are deliberately excluded - 08A
#: showed the model cannot produce them unprompted, so they cannot certify
#: anything (docs/M1-VLN-NAV-08A-RESULT.md §6-§8).
SMOKE_CASES = (
    {
        "id": "SMOKE-EXIT-LEFT",
        "file": _IMG01,
        "target": "出口",
        "target_kind": "目标标识",
        "image": True,
        "expect": "intent",
        "expected_direction": "LEFT",
        "note": "08A U-EXIT-LEFT: 153x132 px 出口/EXIT sign at frame x 0-7%, GT LEFT",
    },
    {
        "id": "SMOKE-EXIT-AHEAD",
        "file": _IMG04,
        "target": "出口",
        "target_kind": "目标标识",
        "image": True,
        "expect": "intent",
        "expected_direction": "STRAIGHT",
        "note": "08A U-EXIT-AHEAD: 89x31 px 出口 sign at frame x 51-55%, GT AHEAD",
    },
    {
        "id": "SMOKE-ABSENT-P07",
        "file": _IMG01,
        "target": "P07",
        "target_kind": "车位编号",
        "image": True,
        "expect": "refused",
        "expected_direction": None,
        "note": "08A N-P07-IMG01: no P07 in the frame; a refusal is the correct outcome",
    },
)


def _gate() -> None:
    if os.environ.get(_SMOKE_ENV) != "1":
        pytest.skip(
            f"{_SMOKE_ENV} is not set to 1; this sends real multimodal requests "
            "to the local inference service"
        )
    if not _IMAGES_DIR.is_dir():
        pytest.skip(f"image directory not found: {_IMAGES_DIR}")


def _emit(record: dict) -> None:
    line = json.dumps(record, ensure_ascii=False)
    print("NAV09 " + line)
    path = os.environ.get(_OUT_ENV, "").strip()
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _real_round(case: dict) -> dict:
    """One real image round, with the on-the-wire image bytes verified."""

    image_path = _IMAGES_DIR / case["file"]
    if not image_path.is_file():
        pytest.skip(f"scene image missing: {image_path}")

    prompt = build_nav_prompt(
        Variant.TARGET_DIRECTION,
        target=case["target"],
        target_kind=case["target_kind"],
        require_identity=True,
        require_evidence=True,
    )
    part = load_image_part(image_path)
    backend = ZDTaichuServerBackend(
        max_new_tokens=400, temperature=0.0, enable_thinking=False, timeout=180.0
    )
    calls, original = _install_recorder()
    try:
        raw = backend.generate_image(str(image_path), prompt)
    finally:
        server_client_module._OPENER.open = original

    assert type(raw) is str
    assert len(calls) == 1, "one round must be exactly one POST"
    payload = json.loads(calls[0]["body"].decode("utf-8"))
    (message,) = payload["messages"]
    encoded = message["content"][0]["image_url"]["url"].partition(";base64,")[2]
    response = json.loads(calls[0]["response_body"].decode("utf-8"))

    return {
        "scene_id": case["id"],
        "target": case["target"],
        "target_kind": case["target_kind"],
        "expected_outcome": case["expect"],
        "expected_direction": case["expected_direction"],
        "gt_note": case["note"],
        "temperature": 0.0,
        "prompt_chars": len(prompt),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "image": part.safe_description(),
        "wire_image_matches_file": hashlib.sha256(base64.b64decode(encoded)).hexdigest()
        == part.sha256,
        "authorization_header_present": calls[0]["authorization"] is not None,
        "usage": response.get("usage"),
        "raw": raw,
    }


@pytest.mark.parametrize("case", SMOKE_CASES, ids=[case["id"] for case in SMOKE_CASES])
def test_real_model_smoke(case: dict) -> None:
    """Real native image -> real model -> judgement -> intent (or a refusal)."""

    _gate()
    record = _real_round(case)
    assert record["wire_image_matches_file"], "the wire image was not the file's bytes"

    outcome: dict = {"refused": None, "intent_payload": None, "direction": None}
    try:
        decision = parse_visual_decision(record["raw"])
        directive = verify_visual_decision(
            decision, expected_identity=case["target"]
        )
        intent = to_agent_intent(
            directive, pose=_SMOKE_POSE, intent_id=f"nav-09-{case['id'].lower()}"
        )
        outcome.update(
            refused=None,
            intent_payload=intent.to_payload(),
            direction=directive.direction,
            position=directive.position,
            identified_as=directive.identified_as,
        )
    except Exception as exc:  # the refusal is a recorded result, not a test error
        outcome.update(refused=f"{type(exc).__name__}: {exc}")

    _emit({**record, "outcome": outcome})

    if case["expect"] == "intent":
        assert outcome["refused"] is None, outcome["refused"]
        assert outcome["direction"] == case["expected_direction"]
        # What was produced is the pre-existing v1 wire format, nothing else.
        assert parse_model_output(outcome["intent_payload"]).action == "parking.move"
    else:
        assert outcome["refused"] is not None, "an absent target must not produce an intent"
        assert outcome["intent_payload"] is None


def test_real_model_smoke_text_only_control() -> None:
    """The same prompt with no image: the default must not become an intent."""

    _gate()
    prompt = build_nav_prompt(
        Variant.TARGET_DIRECTION,
        target="出口",
        target_kind="目标标识",
        require_identity=True,
        require_evidence=True,
    )
    backend = ZDTaichuServerBackend(
        max_new_tokens=400, temperature=0.0, enable_thinking=False, timeout=180.0
    )
    calls, original = _install_recorder()
    try:
        raw = backend.generate(PreparedObservation(text=prompt), "")
    finally:
        server_client_module._OPENER.open = original
    assert len(calls) == 1

    outcome: dict = {"refused": None, "intent_payload": None}
    try:
        decision = parse_visual_decision(raw)
        directive = verify_visual_decision(decision, expected_identity="出口")
        intent = to_agent_intent(directive, pose=_SMOKE_POSE, intent_id="nav-09-text")
        outcome["intent_payload"] = intent.to_payload()
    except Exception as exc:
        outcome["refused"] = f"{type(exc).__name__}: {exc}"

    _emit(
        {
            "scene_id": "SMOKE-TEXT-ONLY",
            "note": "no image part in this request",
            "raw": raw,
            "outcome": outcome,
        }
    )
    assert outcome["refused"] is not None
