"""Skip-gated single-round smoke test against the REAL ZDTaichu5.0-9B model.

This is the corrected form of the smoke script proposed in
``M1-VLN-REAL-MODEL-05A`` (and, before it, ``M1-VLN-REAL-MODEL-04A`` §5). The
05A snippet passed ``PreparedObservation(text="")`` with an empty instruction,
which ``zdtaichu_backend._build_message_parts`` rejects with
``ModelCallError("empty ZDTaichu input")`` *before* the runtime factory is
called - the script could never have reached the model. The input here is
non-empty on both parts.

It is gated exactly like ``tests/integration/test_kernel_host.py``: the test is
marked ``integration`` and skips unless ``VLN_ZDTAICHU_SMOKE=1`` is set
explicitly. Running it loads the real model with ``trust_remote_code=True``,
which executes the model repository's eight custom ``.py`` files, and issues one
``generate`` call. That requires the owner's explicit authorisation (stage gates
G3/G4/G5) and a decision on the ``chat_template.jinja`` version and the
thinking/JSON conflict; by default this test never runs.

It calls the model directly through ``ZDTaichuBackend`` and nothing else: no
Host, no Runtime, no Capability, no Stub Executor, no ``parking.move``
submission, and no inference service. The raw text is recorded verbatim; it is
never repaired, and a parse rejection is reported, not worked around.

Loading a local directory does not consult the Hugging Face hub, so
``HF_HUB_OFFLINE``/``TRANSFORMERS_OFFLINE`` are set only as defence in depth.
Their scope is the huggingface_hub resolution path - they do NOT constrain
arbitrary network calls made by third-party code (the model's
``vision_utils.fetch_image`` issues ``requests.get`` for http(s) image values;
that path is unreachable here because the adapter rejects ``str``/``bytes``
image parts and this test passes no image at all).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_SMOKE_ENV = "VLN_ZDTAICHU_SMOKE"
_MODEL_DIR_ENV = "VLN_ZDTAICHU_MODEL_DIR"
_DEFAULT_MODEL_DIR = Path("/home/gaosong/models/ZDTaichu5.0-9B")

#: Non-empty observation and instruction: the 05A form was rejected pre-load.
_OBSERVATION = "a parking-lot scene: the target slot is ahead-left of the vehicle"
_INSTRUCTION = (
    "Output exactly one JSON object and nothing else, with the keys "
    'contract_version ("1"), intent_id, action ("parking.move") and target '
    '({"x": <metres>, "y": <metres>, "heading": <radians>}).'
)


def _model_dir() -> Path:
    if os.environ.get(_SMOKE_ENV) != "1":
        pytest.skip(
            f"{_SMOKE_ENV} is not set to 1; this test loads the real model and "
            "requires explicit owner authorisation (G3/G4/G5)"
        )
    model_dir = Path(os.environ.get(_MODEL_DIR_ENV, str(_DEFAULT_MODEL_DIR)))
    if not model_dir.is_dir():
        pytest.skip(f"model directory not found: {model_dir}")
    for name in ("config.json", "chat_template.jinja", "model.safetensors.index.json"):
        if not (model_dir / name).is_file():
            pytest.skip(f"model asset missing: {model_dir / name}")
    return model_dir


def test_single_round_text_only_generation() -> None:
    model_dir = _model_dir()

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    from vln.intent import AgentIntent, ModelOutputError, parse_model_output
    from vln.vlm.zdtaichu_backend import ZDTaichuBackend, load_zdtaichu_runtime
    from vln.vlm.zdtaichu_client import PreparedObservation

    backend = ZDTaichuBackend(
        runtime_factory=lambda: load_zdtaichu_runtime(
            model_id=str(model_dir),
            revision=None,
            trust_remote_code=True,
        ),
        max_new_tokens=64,
        do_sample=False,
        enable_thinking=False,
    )

    raw = backend.generate(PreparedObservation(text=_OBSERVATION), _INSTRUCTION)

    assert type(raw) is str
    print(f"RAW OUTPUT ({len(raw)} chars): {raw!r}")

    try:
        intent = parse_model_output(raw)
    except ModelOutputError as exc:
        # A legitimate outcome: the strict parser is fail-closed and the raw
        # text is never repaired. Recorded, not worked around.
        print(f"PARSE REJECTED: {type(exc).__name__}: {exc}")
        return

    assert isinstance(intent, AgentIntent)
    assert intent.action == "parking.move"
    assert json.loads(intent.to_payload())["target"].keys() == {"x", "y", "heading"}
