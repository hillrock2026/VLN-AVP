# VLN-AVP

**Vision-Language Navigation with Action/Verification Pipeline.**

VLN-AVP is the *Intelligence-side* application that turns vision-language
reasoning from **ZDTaichu5.0-9B** into navigation **intent** and action
requests, submits them through the **Agent-Kernel** authorization boundary, and
verifies the execution feedback that comes back. It is the concrete application
scenario for the *Robot Agent Runtime Kernel* defined by RFC v0.3.

> Existing remote tagline: *Vision-Language Navigation with Action and
> Verification Pipeline, powered by ZDTaichu5.0-9B and Agent-Kernel.*

---

## Status

The repository currently contains an NDJSON IPC v1 contract, a Python client,
a test-only stub host, and a C++ host source for a single test-domain
`test.echo` capability through the Agent-Kernel runtime. It does **not** contain
ZDTaichu5.0-9B inference, navigation logic, robot capabilities, or hardware
access. The available test host and test-only capability are not evidence of
K0 completion or production readiness.

---

## Goal

- **Adapt** a vision-language model (ZDTaichu5.0-9B) into a navigation-capable
  Intelligence adapter.
- **Orchestrate** VLN-AVP tasks: observe -> reason -> propose -> request ->
  verify.
- **Propose** navigation intent and action requests only as Agent-Kernel
  `AgentIntent` (contract v1) documents.
- **Verify** execution results and feedback returned by the Kernel.

## Hard boundary (security)

Model output is **intent only**. It must never become a physical command.

```text
Intelligence  (ZDTaichu5.0-9B / VLM / LLM)
      |  AgentIntent
      v
Agent-Kernel  (validate / authorize / schedule)
      |  authorized capability execution
      v
Capability    (navigation / locomotion / ...)
      |  physical execution
      v
Robot
```

Rules that VLN-AVP must obey:

- No direct actuator or hardware access: no motor / joint / servo / PWM /
  torque / velocity / hardware register writes.
- `confidence != authorization` (K0 section 32). A high model confidence never
  bypasses Kernel validation.
- The Kernel is the sole execution authority; the Runtime Event Bus is the sole
  event path.
- The Intelligence -> Kernel submission is an `AgentIntent` (contract v1);
  model-specific types stay on the Intelligence side.

## Non-goals (K0 scope freeze, RFC v0.3 sections 4 and 46)

World Model, ROS2/DDS middleware, VLM internal implementation, ZDTaichu
internals, prompt-framework ownership, semantic planner, SLAM, navigation
algorithm, motion planner, gait controller, hardware driver.

## Repository layout

| Path | Purpose |
|---|---|
| `README.md` | This file. |
| `docs/ARCHITECTURE.md` | Module boundaries, contracts, build/test strategy, risks. |
| `docs/` | Project architecture and interface documentation. Local audit records are not part of this baseline. |
| `configs/` | Runtime / pipeline configuration (see `configs/README.md`). |
| `src/vln/` | VLN-AVP Intelligence-side Python package. |
| `tests/vln/` | Tests for `src/vln`. |
| `pyproject.toml` | Python packaging and pytest configuration. |
| `Agent-Kernel/` | Optional independent local checkout; not tracked or vendored by this repository. |
| `AGENTS.md` | Working agreement for automated agents in this repository. |

## Build and test

### VLN-AVP (Python)

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

`pytest` is configured with `pythonpath = ["src"]`, so the tests also run
directly from a checkout, without installing:

```bash
python -m pytest
```

### Agent-Kernel host (C++)

The C++ host is built against a separately supplied, clean Agent-Kernel source
tree; the independent `Agent-Kernel/` checkout is not included in this
repository's tracked files. See [`runtime_host/README.md`](runtime_host/README.md)
for build inputs and the test-only scope. The Kernel-host integration test
requires a prebuilt executable and skips when it is unavailable.

## Model dependency

ZDTaichu5.0-9B is an **external Intelligence adapter**, not a Kernel component
and not part of this repository. No model weights, inference code, or serving
stack is present or verified here; those are provisioned in a later phase.

## Governance

See `AGENTS.md`. In short: never run `git reset --hard` / `git clean` / force
push / history rewrite; never clean, overwrite, or commit the independently
maintained `Agent-Kernel` work tree without explicit authorization; never
present single-executor experimental results as production safety
certification.

## Roadmap

| Phase | Scope |
|---|---|
| 1 | Establish the repository and IPC/host integration baseline. |
| 2 | Define and implement the Intelligence adapter and Kernel submission boundary. |
| 3 | Implement the VLN-AVP pipeline against a single-executor environment. |
| 4 | Verification, feedback handling, and failure/recovery semantics. |
| 5 | Multi-executor / concurrency hardening and production-readiness review. |

## License

TBD.
