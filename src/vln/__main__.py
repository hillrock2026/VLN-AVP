"""Thin module entry point: ``python -m vln`` runs the **simulated** loop once.

This file only parses the minimal start-up options, builds the application via
:func:`vln.app.build_simulated_loop` and runs it; no loop/parse/validation logic
lives here. See :mod:`vln.app` for the composition.

The inference backend is a deterministic SCRIPTED SIMULATION, not a model:
there is no ZDTaichu5.0-9B, no weights, no network and no GPU. It is enough to
exercise the real loop, the real parser/validator, the real ``HostClient`` and a
real ``kernel_host`` subprocess.

The host executable must be supplied (``--host-exe`` or ``VLN_KERNEL_HOST_EXE``).
When it is absent the program fails with a clear message instead of silently
doing nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Allow ``python -m vln`` (and ``python src/vln/__main__.py``) to run from a
# checkout without installing the package, mirroring runtime_host/stub_host.py.
_REPO_SRC = Path(__file__).resolve().parents[1]
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from vln.app import build_simulated_loop  # noqa: E402
from vln.client import HostClient  # noqa: E402
from vln.pipeline import DEFAULT_MAX_ROUNDS  # noqa: E402

_HOST_EXE_ENV = "VLN_KERNEL_HOST_EXE"


class _ScriptedPlanBackend:
    """SIMULATION-ONLY inference backend: a fixed list of target x values.

    It is explicitly *not* a model - it performs no inference and claims no
    visual understanding. Round ``i`` returns a valid ``parking.move`` intent
    for ``plan[i]``; once the plan is exhausted it returns empty text, which the
    loop treats as the model's explicit stop.
    """

    def __init__(self, targets: list[float]) -> None:
        self._targets = list(targets)
        self._index = 0

    def generate(self, observation: object, instruction: str) -> str:
        if self._index >= len(self._targets):
            return ""
        x = self._targets[self._index]
        self._index += 1
        return json.dumps(
            {
                "contract_version": "1",
                "intent_id": f"intent-sim-{self._index}",
                "action": "parking.move",
                "target": {"x": x, "y": -2.25, "heading": 0.5},
            },
            separators=(",", ":"),
        )


def _parse_plan(text: str) -> list[float]:
    return [float(part) for part in text.split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vln",
        description="Run the SIMULATED VLN-AVP loop (no real model is loaded).",
    )
    parser.add_argument("--instruction", default="park at the target")
    parser.add_argument(
        "--observation",
        default="simulated parking-lot scene (no camera in this phase)",
    )
    parser.add_argument("--plan", default="1.0,2.0", help="comma-separated target x values")
    parser.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS)
    parser.add_argument(
        "--host-exe",
        default=os.environ.get(_HOST_EXE_ENV),
        help=f"path to the compiled kernel_host (default: ${_HOST_EXE_ENV})",
    )
    args = parser.parse_args(argv)

    if not args.host_exe:
        print(
            f"error: no host executable; pass --host-exe <path> or set ${_HOST_EXE_ENV}",
            file=sys.stderr,
        )
        return 2

    app = build_simulated_loop(
        backend_factory=lambda: _ScriptedPlanBackend(_parse_plan(args.plan)),
        host_client_factory=lambda: HostClient([args.host_exe]),
        instruction=args.instruction,
        max_rounds=args.max_rounds,
    )

    result = app.run(args.observation)
    last = result.last_response
    summary = {
        "stop_reason": result.stop_reason,
        "rounds_executed": len(result.responses),
        "last_ok": None if last is None else last.ok,
        "note": "simulated: fake backend + kernel_host parking.move stub; not real inference",
    }
    print(json.dumps(summary, separators=(",", ":"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
