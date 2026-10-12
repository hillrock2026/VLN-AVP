# VLN-AVP Architecture

**Status:** Phase 1 (initialization) — boundaries and strategy only. No VLN-AVP
code is implemented yet.

**Inputs verified in this workspace:**

- `docs/Robot Agent Kernel + ZDTaichu5.0-9B VLN-AVP System Architecture RFC v0.3.docx`
- `docs/Robot Agent Kernel K0 Contract Freeze.txt` (and the `.docx`)
- `Agent-Kernel/standards/K0_CONTRACT_SPEC.md`
- `Agent-Kernel/include/agent_kernel/contract/{k0_contract,agent_intent,capability}.hpp`
- `Agent-Kernel/runtime/include/runtime.h`

---

## 1. Layering and the execution-authority boundary

The system has four layers. VLN-AVP owns only the top layer.

```text
+--------------------------------------------------------------+
| Intelligence Layer  (owned by VLN-AVP)                        |
|   ZDTaichu5.0-9B / VLM / LLM                                  |
|   vision understanding, language reasoning,                  |
|   semantic planning, goal decomposition                      |
+--------------------------------------------------------------+
                       |  AgentIntent (contract v1)
                       v
+--------------------------------------------------------------+
| Robot Agent Kernel  (owned by Agent-Kernel)                  |
|   intent validation, task lifecycle, execution authority,    |
|   capability registry/composition, runtime context,          |
|   runtime events, resource ownership, cancellation,          |
|   preemption, runtime recovery                               |
+--------------------------------------------------------------+
                       |  authorized capability execution
                       v
+--------------------------------------------------------------+
| Robot Capability Layer                                       |
|   navigation, locomotion, manipulation, perception adapter,  |
|   hardware adapter                                           |
+--------------------------------------------------------------+
                       |  physical execution
                       v
                    Physical Robot
```

Frozen principle (K0 section 45):

- Intelligence decides **what should be done**.
- Kernel decides **whether and how** it may execute.
- Capability performs the operation.
- Robot performs the physical action.

VLN-AVP sits entirely above the Kernel. It may **submit** intent and **observe**
results/events; it may never authorize, schedule, or execute.

## 2. Repository boundary: VLN-AVP vs Agent-Kernel

- **Agent-Kernel** (https://github.com/hillrock2026/Agent-Kernel) is maintained
  independently. In this project it is intended to be pinned into VLN-AVP as a
  Git **submodule** at a fixed commit.
- **VLN-AVP** (this repository) owns the Intelligence adapter, VLN task
  orchestration, action-request construction, execution-feedback handling, and
  result verification.

### Verified local state (2026-10-09)

- `Agent-Kernel/` here is a **standalone clone** (its own `.git`, `origin` =
  Agent-Kernel), checked out at `dcd1341d768cacd50af640fb47ab627dbf3e1f5e`
  (`main`, "Create curated project baseline").
- That clone has a **large uncommitted working tree** (K0 remediation
  modifications plus untracked `standards/schemas/`,
  `include/agent_kernel/contract/`, `docs/audit/`, K0 tests, ...). This work is
  protected and must not be reset, cleaned, or committed by VLN-AVP tooling.
- `Agent-Kernel/` is therefore **not yet a submodule**. Converting it requires
  committing/pinning a Kernel revision, which is an external, explicitly
  authorized action. Until then, do not `git add Agent-Kernel`.

## 3. Planned module boundaries (`src/vln/`)

These are the intended responsibilities. Phase 1 creates only the package
placeholder; no module is implemented.

| Module (planned) | Responsibility | Must not |
|---|---|---|
| `vln.vlm` (adapter) | ZDTaichu5.0-9B access (local or remote serving); image/language -> structured proposal | touch actuators; reach into Kernel internals |
| `vln.intent` | Convert a model proposal into an `AgentIntent` (contract v1) document | invent fields outside the frozen schema |
| `vln.orchestrator` | VLN-AVP task loop (observe -> reason -> propose -> request -> verify) | authorize or schedule execution itself |
| `vln.kernel_client` | Submit intent to the Kernel and receive `ExecutionResult` / `RuntimeEvent` | call capabilities directly |
| `vln.verify` | Verify execution results/feedback against the requested intent | reinterpret runtime state as a semantic goal |
| `vln.config` | Load `configs/` | — |

Cross-cutting rule: **no `vln.*` module may access hardware, actuators, or a
physical execution path.** The only outbound artifact is an `AgentIntent`.

## 4. Contracts and data flow

Frozen K0 contracts (contract version `"1"`), verified in
`Agent-Kernel/standards/schemas/` and `Agent-Kernel/include/agent_kernel/contract/`:

| Contract | Schema | C++ |
|---|---|---|
| AgentIntent | `agent_intent.schema.json` | `ak::contract::AgentIntent` |
| Capability | `capability.schema.json` | `ak::contract::CapabilityDescriptor` |
| CapabilityWorkflow | `capability_workflow.schema.json` | `ak::contract::CapabilityWorkflow` |
| RuntimeContext | `runtime_context.schema.json` | `ak::contract::RuntimeContext` |
| ExecutionResult | `execution_result.schema.json` | `ak::ExecutionResult` |
| RuntimeEvent | `runtime_event.schema.json` | `ak::RuntimeEvent` |

`AgentIntent` fields (`agent_intent.hpp`): `id`, `type`, `payload` (opaque JSON
object), `constraints` (string list), `confidence` (double in [0,1]),
`metadata` (opaque JSON object), plus `contract_version`. `confidence` never
grants authorization. The Kernel public surface VLN-AVP will use is
`ak::runtime::Runtime::Run(ak::Session&)`,
`Runtime::RegisterCapability(...)`, and
`Runtime::SubscribeToRuntimeEvent(...)` (observation only).

Intended VLN-AVP data flow:

```text
observation -> vln.vlm (proposal) -> vln.intent (AgentIntent v1)
            -> vln.kernel_client (Kernel Runtime)
            -> ExecutionResult + RuntimeEvent
            -> vln.verify (result) -> next observation
```

## 5. Build approach

**VLN-AVP (Python).** Python package under `src/` (src-layout), packaged with
`pyproject.toml` (setuptools). Verified local interpreter: CPython 3.13.9
(Anaconda), `pytest` 8.4.2. Install for development with
`python -m pip install -e ".[dev]"`. The skeleton is dependency-free; model and
Kernel-client dependencies are added only when a phase requires them.

**Agent-Kernel (C++).** A separate C++20 project (CMake; `/W4 /WX` on MSVC),
built by its own project and not by VLN-AVP tooling. Verified toolchain on this
machine: Visual Studio 18 Community, MSVC toolset 14.51.36231, bundled
CMake/Ninja, GTest 1.11.0 from a local Anaconda `Library` directory. The Kernel
README documents the default green path
(`-DAK_BUILD_TESTS=ON -DAK_BUILD_PROTOTYPE=OFF`).

**Integration mechanism (open).** How the Python Intelligence side talks to the
C++ Kernel is not decided. Candidates: an in-process bridge, a C++ bridge
executable over JSON/IPC, or a thin Python binding. This is a Phase-2 decision;
no mechanism is implemented or assumed here.

## 6. Test strategy

- **Unit tests** (`tests/vln/`) for pure Intelligence-side logic: intent
  construction, verification, orchestration state.
- **Contract conformance**: every `AgentIntent` VLN-AVP emits must validate
  against `Agent-Kernel/standards/schemas/agent_intent.schema.json` (v1).
- **Kernel integration** (later phase): exercised against the pinned
  Agent-Kernel submodule and its own built `Runtime`.
- **Smoke test**: the Phase-1 skeleton must import and pass `python -m pytest`.

Tests must run without a robot. Any test requiring a Kernel session, model
weights, or hardware must skip cleanly when those are absent.

## 7. Model dependency

ZDTaichu5.0-9B is the reference Intelligence model. It is an **external
adapter**, not a Kernel component (K0-RULE-001). No weights, tokenizer,
inference code, or serving endpoint is present or verified in this repository.
Model provisioning is a later-phase item; nothing here assumes a specific
serving framework (the local environment currently has `torch` but not
`transformers`).

## 8. Security constraints

- **No direct physical control** (K0-RULE-004): Intelligence never calls motor /
  joint / servo / PWM / torque / velocity / hardware register.
- **Model independence** (K0-RULE-001): no ZDTaichu-specific type may enter the
  Kernel contract; translation happens on the Intelligence side.
- **Middleware independence** (K0-RULE-002): no ROS2/DDS/ZeroMQ/gRPC/WebSocket
  in the Kernel contract.
- **No World Model** (K0-RULE-003): map/object/scene are not Kernel primitives.
- **`confidence != authorization`** (K0 section 32).
- **Sole authority**: the Kernel owns execution; the Runtime Event Bus is the
  only event path.
- **Runtime recovery vs semantic recovery**: the Kernel may report e.g.
  `TARGET_NOT_FOUND` but must not choose a semantic alternative; replanning is
  Intelligence-side.

## 9. Known risks and open decisions

1. **Submodule pinning is blocked.** `Agent-Kernel/` here has uncommitted work
   that must be preserved; pinning a revision is an authorized external action.
   Until then the Kernel dependency is a local checkout, not a reproducible pin.
2. **K0 concurrency/lifecycle risks are not resolved.** Per project principle 8,
   verifiable VLN functionality may proceed in a **single-executor** experiment
   before all K0 issues are fixed. Known risks must be recorded, and results
   must not be described as production safety certification.
3. **Integration mechanism undecided** (section 5).
4. **Language split**: this architecture assigns the Intelligence side to Python
   and the authorization boundary to the C++ Kernel; the split and the bridge
   are subject to confirmation.
5. **License** is TBD.

## 10. Phase roadmap

| Phase | Scope | Exit evidence |
|---|---|---|
| 1 | Initialize VLN-AVP skeleton and boundaries. | This document + minimal package tree; smoke test passes. |
| 2 | Intelligence adapter + Kernel submission boundary. | Adapter interface + intent construction with schema-conformance tests. |
| 3 | VLN-AVP pipeline in a single-executor environment. | End-to-end run over a pinned Kernel revision; recorded risks. |
| 4 | Verification and feedback / failure-recovery semantics. | Result-verification tests; documented failure/recovery behavior. |
| 5 | Concurrency hardening / production-readiness review. | Multi-executor validation and independent audit. |
