"""Skip-gated prompt experiment against the REAL ZDTaichu5.0-9B service.

What this answers: 06A showed the image reaches the model (wire-level proof) and
that the model can answer a visual question (IMG-01 -> C, IMG-02 -> A), yet the
*same* two images produced template echo and ``target {x:0,y:0,heading:0}`` under
the navigation instruction. This file isolates whether the prompt, rather than the
image path, caused that.

Design: one variable at a time. ``temperature`` is 0 everywhere, the image path
and the client are unchanged, and the matrix below fixes ``(variant, scene,
thinking)`` explicitly - so a difference between two rows can only come from the
field that differs.

  * BASELINE is 06A's prompt verbatim (it contains the ``<字符串>``/``<数值>``
    placeholders), kept as the control.
  * DETEMPLATED keeps the contract shape but removes every placeholder and sampled
    value, and adds anti-copy / anti-fabrication rules.
  * ABSTENTION asks for a staged observation -> target check -> decision -> prose
    judgement and no JSON at all, because ``AgentIntent`` v1 cannot express
    "target not visible". It is expected to fail ``parse_model_output`` and that
    failure is a recorded result, not a bug.
  * STRICT fixes the ``intent_id`` to a caller-owned literal, gives a minimal
    format definition with no sampled values, and bans placeholder echo and
    all-zero coordinates outright.
  * the ``thinking=True`` rows re-run two of those with only that flag changed.

Nothing is asserted about the model's *content*: a wrong or evasive answer is a
real result, and this file records it rather than manufacturing a pass. The
service is contacted on the confirmed loopback endpoint only and is never
started, stopped or reconfigured.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path

import pytest

from vln.intent import AgentIntent, ModelOutputError, parse_model_output
from vln.vlm import server_client as server_client_module
from vln.vlm.image_input import load_image_part
from vln.vlm.nav_prompt import (
    GROUNDING_QUESTION,
    Variant,
    build_nav_prompt,
)
from vln.vlm.server_client import ZDTaichuServerBackend
from vln.vlm.zdtaichu_client import PreparedObservation

pytestmark = pytest.mark.integration

_EXPERIMENT_ENV = "VLN_ZDTAICHU_NAV_EXPERIMENT"
_ONLY_ENV = "VLN_ZDTAICHU_NAV_ONLY"
_IMAGES_DIR = Path(__file__).resolve().parents[2] / "images"

#: Files plus the letter that is actually on the columns and the bay identifiers
#: that are actually legible (read from zoomed crops in 06A). None of the four
#: frames carries a ``P07`` marking, so "not visible" is the only correct target
#: conclusion; a claim to the contrary is a fabrication.
SCENES = {
    "IMG-01": {"file": "17931c01d3fda4038c76944a334b3aef.png", "column_letter": "C",
               "legible_bay_ids": ()},
    "IMG-02": {"file": "7328a8047ee41f088cceadaa7daa9b6d.png", "column_letter": "A",
               "legible_bay_ids": ("D65",)},
    "IMG-03": {"file": "7ea84b439661950fcb5ec85d81011bfd.png", "column_letter": "B",
               "legible_bay_ids": ("D0x",)},
    "IMG-04": {"file": "9a6908511ef1211af2ae8483c103bb63.png", "column_letter": "C",
               "legible_bay_ids": ("316",)},
}

#: (variant, scene, thinking, max_new_tokens) - the whole experiment, in one table.
MATRIX = (
    (Variant.BASELINE, "IMG-01", False, 320),
    (Variant.BASELINE, "IMG-02", False, 320),
    (Variant.DETEMPLATED, "IMG-01", False, 320),
    (Variant.DETEMPLATED, "IMG-02", False, 320),
    (Variant.DETEMPLATED, "IMG-03", False, 320),
    (Variant.DETEMPLATED, "IMG-04", False, 320),
    (Variant.ABSTENTION, "IMG-01", False, 320),
    (Variant.ABSTENTION, "IMG-02", False, 320),
    (Variant.STRICT, "IMG-01", False, 320),
    (Variant.STRICT, "IMG-02", False, 320),
    (Variant.STRICT, "IMG-03", False, 320),
    (Variant.STRICT, "IMG-04", False, 320),
    # Thinking ablation: same prompts and images, only ``enable_thinking`` changes.
    (Variant.STRICT, "IMG-01", True, 512),
    (Variant.STRICT, "IMG-02", True, 512),
    (Variant.ABSTENTION, "IMG-01", True, 512),
    (Variant.ABSTENTION, "IMG-02", True, 512),
)

#: phrasings that count as the model declining to name a location.
_ABSTENTION_MARKERS = ("无法确定", "不能确定", "无法确认", "不可见", "未出现", "没有出现",
                       "看不到", "无法判断", "cannot", "not visible")

#: visual footholds the answer may legitimately cite.
_EVIDENCE_PATTERNS = {
    "column_letter": re.compile(r"立柱|柱子|区域标识"),
    "bay_id": re.compile(r"车位编号|编号|D6\d|D0\d|316"),
    "exit_sign": re.compile(r"EXIT|出口"),
    "arrow": re.compile(r"箭头|直行|左转|右转"),
    "obstacle": re.compile(r"挡车器|护栏|闸门|障碍"),
}


class _RecordingResponse:
    """Tee ``read`` off the real response so the wire body can be recorded."""

    def __init__(self, response, sink: dict) -> None:
        self._response = response
        self._sink = sink

    def read(self, limit: int | None = None) -> bytes:
        data = self._response.read(limit)
        self._sink["response_body"] = data
        return data

    def __enter__(self) -> "_RecordingResponse":
        self._response.__enter__()
        return self

    def __exit__(self, *exc: object) -> object:
        return self._response.__exit__(*exc)

    def __getattr__(self, name: str) -> object:
        return getattr(self._response, name)


def _install_recorder():
    """Wrap the real opener to record each POST, then send it unchanged."""

    original = server_client_module._OPENER.open
    calls: list = []

    def _open(request, timeout=None):
        calls.append({"body": request.data})
        return _RecordingResponse(original(request, timeout=timeout), calls[-1])

    server_client_module._OPENER.open = _open
    return calls, original


def _gate() -> None:
    if os.environ.get(_EXPERIMENT_ENV) != "1":
        pytest.skip(
            f"{_EXPERIMENT_ENV} is not set to 1; this sends real multimodal "
            "requests to the local inference service"
        )
    if not _IMAGES_DIR.is_dir():
        pytest.skip(f"image directory not found: {_IMAGES_DIR}")


def _wanted() -> list:
    """Optionally narrow the matrix through ``VLN_ZDTAICHU_NAV_ONLY``.

    Tokens are comma-separated and matched exactly, either as a variant name
    (every row of that variant) or as ``variant:SCENE``. Exact matching keeps a
    narrow pilot from silently expanding into the full matrix.
    """

    only = os.environ.get(_ONLY_ENV, "").strip().lower()
    if not only:
        return list(MATRIX)
    tokens = {token.strip() for token in only.split(",") if token.strip()}
    selected = [
        row for row in MATRIX if row[0].lower() in tokens or f"{row[0]}:{row[1]}".lower() in tokens
    ]
    if not selected:
        pytest.fail(f"${_ONLY_ENV}={only!r} matched no matrix row")
    return selected


def _image_round(variant: str, scene_id: str, thinking: bool, max_new_tokens: int):
    """Send exactly one image round and return (prompt, part, raw, sample)."""

    scene = SCENES[scene_id]
    image_path = _IMAGES_DIR / scene["file"]
    if not image_path.is_file():
        pytest.skip(f"scene image missing: {image_path}")

    prompt = build_nav_prompt(variant)
    part = load_image_part(image_path)
    backend = ZDTaichuServerBackend(
        max_new_tokens=max_new_tokens,
        temperature=0.0,
        enable_thinking=thinking,
        timeout=180.0,
    )

    calls, original = _install_recorder()
    try:
        raw = backend.generate_image(str(image_path), prompt)
    finally:
        server_client_module._OPENER.open = original

    assert type(raw) is str
    assert len(calls) == 1, "one round must be exactly one POST"

    body = calls[0]["body"]
    payload = json.loads(body.decode("utf-8"))
    (message,) = payload["messages"]
    encoded = message["content"][0]["image_url"]["url"].partition(";base64,")[2]
    sent = hashlib.sha256(base64.b64decode(encoded)).hexdigest()

    response = json.loads(calls[0]["response_body"].decode("utf-8"))
    choice = response["choices"][0]

    sample = {
        "variant": variant,
        "scene_id": scene_id,
        "thinking": thinking,
        "temperature": 0.0,
        "max_new_tokens": max_new_tokens,
        "prompt_chars": len(prompt),
        "image_sha256": part.sha256,
        "wire_image_matches_file": sent == part.sha256,
        "content_part_types": [item["type"] for item in message["content"]],
        "usage": response.get("usage"),
        "finish_reason": choice.get("finish_reason"),
        "reasoning_content_chars": len(choice["message"].get("reasoning_content") or ""),
        "raw": raw,
    }
    return scene, prompt, sample


def _classify(sample: dict, scene: dict) -> dict:
    """Score one sample on the 06A failure modes and on the evidence it cites."""

    raw = sample["raw"]
    stripped = raw.strip()

    parsed = None
    parse_error = None
    try:
        parsed = parse_model_output(raw)
    except ModelOutputError as exc:
        parse_error = {"error": type(exc).__name__, "message": str(exc)[:200]}

    zero_target = None
    if parsed is not None:
        zero_target = (
            parsed.target.x == 0 and parsed.target.y == 0 and parsed.target.heading == 0
        )

    lowered = raw.lower()
    return {
        "template_echo": bool(re.search(r"<[^>]{0,12}>", raw))
        or "字符串" in raw
        or "数值" in raw,
        "echoed_field_names_as_values": '"intent_id":"intent_id"' in raw.replace(" ", ""),
        "all_zero_target": zero_target,
        "abstained": stripped == "" or any(m.lower() in lowered for m in _ABSTENTION_MARKERS),
        "claimed_target_found": bool(
            re.search(r"已(找到|到达|确认).{0,6}P07|found.{0,10}P07", raw, re.IGNORECASE)
        ),
        "cites_visual_evidence": {
            name: bool(pattern.search(raw)) for name, pattern in _EVIDENCE_PATTERNS.items()
        },
        "mentions_the_true_column_letter": scene["column_letter"] in raw,
        "mentions_a_real_bay_id": any(
            bay.replace("x", "") in raw for bay in scene["legible_bay_ids"]
        ),
        "mentions_the_target_label": "P07" in raw,
        "parse_model_output": "ok" if parsed is not None else parse_error,
        "agent_intent": (
            None
            if parsed is None
            else {
                "intent_id": parsed.intent_id,
                "action": parsed.action,
                "target": {"x": parsed.target.x, "y": parsed.target.y,
                           "heading": parsed.target.heading},
                "round_trips_through_from_payload": AgentIntent.from_payload(raw)
                .to_object()
                == parsed.to_object(),
                "note": "contract-valid syntax only; not a measured coordinate",
            }
        ),
    }


def _emit(record: dict) -> None:
    print("NAV EVIDENCE " + json.dumps(record, ensure_ascii=False))


@pytest.mark.parametrize("variant,scene_id,thinking,max_new_tokens", _wanted())
def test_prompt_matrix(
    variant: str, scene_id: str, thinking: bool, max_new_tokens: int
) -> None:
    _gate()
    scene, _prompt, sample = _image_round(variant, scene_id, thinking, max_new_tokens)
    assert sample["wire_image_matches_file"], "the wire image was not the file's bytes"
    _emit({"phase": "prompt-matrix", **sample, "scored": _classify(sample, scene)})


@pytest.mark.parametrize("scene_id", ("IMG-01", "IMG-02"))
def test_grounding_probe_survives_the_new_prompts(scene_id: str) -> None:
    """The 06A probe, unchanged: IMG-01 -> C, IMG-02 -> A. Records non-regression."""

    _gate()
    scene = SCENES[scene_id]
    image_path = _IMAGES_DIR / scene["file"]
    if not image_path.is_file():
        pytest.skip(f"scene image missing: {image_path}")

    part = load_image_part(image_path)
    backend = ZDTaichuServerBackend(
        max_new_tokens=64, temperature=0.0, enable_thinking=False, timeout=180.0
    )
    calls, original = _install_recorder()
    try:
        raw = backend.generate_image(str(image_path), GROUNDING_QUESTION)
    finally:
        server_client_module._OPENER.open = original
    assert len(calls) == 1

    answer = raw.strip()
    _emit(
        {
            "phase": "grounding-probe",
            "scene_id": scene_id,
            "image_sha256": part.sha256,
            "question": GROUNDING_QUESTION,
            "expected_letter_from_the_pixels": scene["column_letter"],
            "raw": raw,
            "answer_matches_the_pixels": answer.upper() == scene["column_letter"],
        }
    )


def test_text_only_control() -> None:
    """Same prompts with no image: shows how much of an answer is the image."""

    _gate()
    backend = ZDTaichuServerBackend(
        max_new_tokens=320, temperature=0.0, enable_thinking=False, timeout=180.0
    )
    prompts = {
        "strict": build_nav_prompt(Variant.STRICT),
        "grounding": GROUNDING_QUESTION,
    }
    answers = {}
    calls, original = _install_recorder()
    try:
        for name, prompt in prompts.items():
            answers[name] = backend.generate(PreparedObservation(text=prompt), "")
    finally:
        server_client_module._OPENER.open = original

    assert len(calls) == 2
    _emit(
        {
            "phase": "text-only-control",
            "note": "no image part in these two requests",
            "answers_without_any_image": answers,
        }
    )
