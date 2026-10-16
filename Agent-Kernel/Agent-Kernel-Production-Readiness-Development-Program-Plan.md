# Agent Kernel Production Readiness Development Program Plan

**Revision:** Rev1.0  
**Date:** 2026-09-03  
**Status:** PROGRAM BASELINE — READY FOR OWNER REVIEW  
**Plan Type:** Project-level execution and governance plan  
**Scope:** Repository Baseline, Production Model Provider, Production Composition, Runtime Multi-Invocation  
**Workspace:** Ubuntu repository at `/home/liu/workspace/Agentic_Program/AgentRuntimeKernel/agent-kernel`

> This document is the working baseline for the next Agent Kernel development period.
> It defines scope, sequencing, responsibilities, evidence, review gates, and completion
> criteria. It does not itself authorize a specific backend selection, dependency
> installation, credential change, architecture rewrite, or production deployment.

---

# 1. Program Objective

The program shall move Agent Kernel from:

```text
well-specified subsystem implementations
+ deterministic test-side integration
+ bounded Runtime-backed execution
```

to:

```text
reproducible Ubuntu engineering baseline
+ one production Model provider
+ one production Agent composition root
+ governed Runtime multi-invocation semantics
+ one unified, bounded, production-representative Agent path
```

The target is not a distributed or fully autonomous Agent platform. The target is a
small, verifiable, production-representative kernel that can be built from a clean
checkout, invoke a real model, execute approved capabilities through Runtime more than
once, update Context, and terminate deterministically.

---

# 2. Current Baseline

The plan starts from the following repository-grounded state:

1. Foundation, Agent, Memory, Context, Planner, Prompt, Tool, Model abstraction, and
   Runtime implementations exist.
2. `RuntimePublicApiAdapter`, `RuntimeBackedExecutionComposition`,
   `ModelToRuntimeDecisionComposition`, and `AgentContinuationComposition` exist and
   have historical acceptance evidence.
3. First Working Agent provides a bounded loop, but uses test-scoped Model and Tool
   execution seams and does not use Runtime.
4. Runtime-backed compositions use the production boundaries, but production wiring
   exists only in tests and continuation is limited to one opportunity.
5. No production Model provider or production Agent executable exists.
6. Runtime is currently one-shot: `Runtime::Run` requires `kCreated`.
7. The repository has no Git commit baseline; current files are untracked.
8. Root CMake contains damaged or missing variable expansions in several locations.
9. Ubuntu has `g++` and `make`, but `cmake`, `ninja`, and `clang++` are not currently
   available on `PATH`.
10. All 76 production `.cpp` files compile individually with Ubuntu `g++`, C++20, and
    `-Wall -Wextra -Wpedantic -Werror`; full CMake/CTest verification has not yet been
    reproduced on this Ubuntu environment.
11. Existing GitHub Actions workflows are placeholders.
12. The latest provider discovery is Ubuntu-oriented, while the older implementation
    plan remains coupled to WinHTTP and Windows SDK assumptions.

Historical acceptance reports remain useful evidence, but they do not replace a fresh
Ubuntu build and test result.

---

# 3. Program Scope

## 3.1 In scope

### Workstream B — Repository Engineering Baseline

- Git hygiene and initial trustworthy baseline.
- Root CMake repair.
- Clean Ubuntu configure, build, test, and install verification.
- Dependency bootstrap documentation.
- Executable Ubuntu CI.
- Accurate README and documentation index.
- Removal or exclusion of generated build artifacts from source control scope.

### Workstream P — Production Model Provider

- Resolve the Ubuntu backend and transport governance gap.
- Implement one production `ak::model::Model` provider.
- Preserve provider-neutral Model boundaries.
- Add deterministic unit tests and opt-in live inference verification.
- Prohibit credential leakage and synthetic-success fallbacks.

### Workstream R — Runtime Multi-Invocation

- Define and implement reusable Runtime service lifecycle semantics.
- Allow multiple bounded Session/invocation executions without reconstructing the
  complete Runtime service graph for every Agent decision.
- Preserve Scheduler, Executor, Resolver, EventBus, and Core ownership boundaries.
- Add compatibility, isolation, failure, and repeated-invocation tests.

### Workstream C — Production Composition

- Create one production composition root.
- Wire Prompt, Model, ModelResult interpretation, Runtime adapter, Runtime, Context,
  Planner/Memory/Tool surfaces as required by the approved composition contract.
- Provide a minimal executable entry point.
- Converge First Working Agent and Runtime-backed execution into one production path.
- Add a bounded multi-cycle execution policy after Runtime multi-invocation is ready.

## 3.2 Explicitly out of scope

Unless separately authorized, this program shall not introduce:

- distributed execution;
- multi-Agent orchestration;
- daemon/service deployment;
- background autonomous operation;
- streaming model responses;
- provider routing, fallback, marketplace, or load balancing;
- generalized dependency injection framework;
- persistent database-backed Memory or Context;
- unbounded Agent loops;
- automatic retries without an explicit retry contract;
- plugin ABI redesign;
- Runtime internal types in Agent-facing interfaces;
- provider SDK or transport types in Agent-facing interfaces.

---

# 4. Roles and Separation of Duties

## 4.1 Owner

The Owner:

- accepts or rejects this program baseline;
- selects the production model backend when a choice is required;
- authorizes dependency installation, environment changes, credentials, and live
  endpoint use;
- authorizes implementation after required plan/review gates;
- decides on unresolved scope or architecture alternatives.

## 4.2 Project Lead — Copilot CLI

The Project Lead:

- maintains this program plan and task dependency graph;
- inspects repository evidence before issuing each task;
- defines exact task scope, protected surfaces, acceptance criteria, and test commands;
- writes implementation prompts for OpenCode + DeepSeek;
- writes independent review prompts for TRAE + GLM-5.2;
- checks that implementation and review evidence refer to the same revision;
- adjudicates review findings;
- requests corrections when evidence is insufficient;
- performs final integration verification and recommends closure to the Owner;
- prevents scope creep and conflicting parallel edits.

The Project Lead does not treat an implementer report or reviewer verdict as sufficient
on its own. Closure requires repository evidence and reproducible validation.

## 4.3 Implementer — OpenCode + DeepSeek

The Implementer:

- changes code, tests, CMake, and directly related documentation;
- follows the task prompt and existing repository conventions;
- performs the smallest sufficient validation and reports exact commands/results;
- records all changed files and explains contract-to-code traceability;
- does not self-expand scope;
- does not mark its own work independently accepted;
- does not silently install dependencies, alter credentials, or change backend choice.

## 4.4 Independent Reviewer — TRAE + GLM-5.2

The Independent Reviewer:

- reviews the actual diff and referenced authority;
- checks correctness, architecture boundaries, regression risk, test sufficiency,
  portability, and documentation accuracy;
- reproduces or independently verifies important evidence when feasible;
- reports findings by severity and stable finding ID;
- distinguishes defects from observations and future enhancements;
- does not modify implementation while acting as reviewer;
- does not approve based only on the implementation report.

## 4.5 Responsibility matrix

| Activity | Owner | Project Lead | OpenCode + DeepSeek | TRAE + GLM-5.2 |
|---|---:|---:|---:|---:|
| Program scope approval | A | R | C | C |
| Backend selection | A/R | C | I | C |
| Task decomposition | C | A/R | I | I |
| Implementation prompt | I | A/R | C | I |
| Code/document implementation | I | C | A/R | I |
| Implementation self-test | I | C | A/R | I |
| Independent review | I | C | I | A/R |
| Finding adjudication | C | A/R | C | C |
| Correction implementation | I | C | A/R | I |
| Closure recommendation | C | A/R | I | C |
| Final program acceptance | A/R | C | I | I |

Legend: A = Accountable, R = Responsible, C = Consulted, I = Informed.

---

# 5. Evidence and Truth Rules

Evidence priority for this program is:

```text
fresh command output / executable behavior
    >
current source, tests, and build graph
    >
accepted authority and contract
    >
implementation or review report
    >
historical status summary
    >
author claim
```

Rules:

1. A test result must identify the source revision or working-tree state it validates.
2. Historical Windows build evidence cannot prove the Ubuntu baseline.
3. Individual source compilation cannot prove linking, CMake correctness, or CTest
   behavior.
4. A review `PASS` cannot close work if required tests were not run or could not run.
5. A passing test does not authorize behavior outside the test's stated scope.
6. Documentation must describe current repository state, not planned or historical
   state as if it were current.
7. Secrets, tokens, endpoint credentials, and raw provider responses containing
   sensitive data must not be committed or copied into reports.

---

# 6. Standard Task Lifecycle

Every implementation unit follows this lifecycle:

```text
PLANNED
  -> BASELINE VERIFIED
  -> PROMPT ISSUED
  -> IMPLEMENTING
  -> IMPLEMENTER VERIFIED
  -> INDEPENDENT REVIEW
  -> CORRECTION (if findings)
  -> RE-REVIEW
  -> PROJECT LEAD ACCEPTANCE
  -> OWNER GATE (when required)
  -> CLOSED
```

## 6.1 Required task artifacts

Each non-trivial implementation task produces:

1. Project Lead implementation prompt.
2. Code/test/document changes.
3. Implementer report containing:
   - scope completed;
   - changed files;
   - design decisions;
   - exact validation commands and results;
   - known residuals;
   - statement of untouched protected surfaces.
4. Project Lead review prompt.
5. Independent review report.
6. Correction report and re-review when findings exist.
7. Project Lead acceptance record.

Reports should be concise and evidence-oriented. A new document is not required for a
small correction when the diff, review findings, and validation record are sufficient.

## 6.2 Finding severity

| Severity | Meaning | Closure effect |
|---|---|---|
| Critical | Security, data loss, authority violation, or fundamentally invalid design | Blocks immediately |
| Major | Required behavior missing, broken boundary, non-reproducible build, serious regression | Blocks |
| Minor | Localized correctness, test, portability, or documentation defect | Blocks task unless explicitly deferred by Owner |
| Observation | Non-blocking improvement or future concern | Recorded; does not block |

No finding may be silently downgraded. The Project Lead records the disposition.

---

# 7. Dependency and Delivery Strategy

## 7.1 Program dependency graph

```text
B0 Repository Baseline
   ├──> P0 Provider Re-baselining ──> P1 Provider Implementation ──┐
   │                                                               ├──> C1 Production Bootstrap
   └──> R0 Multi-Invocation Contract ──> R1 Runtime Implementation ┘
                                                                    |
                                                                    v
                                                        C2 Unified Bounded Agent
                                                                    |
                                                                    v
                                                        F0 Final Qualification
```

## 7.2 Parallelism policy

After Workstream B is closed:

- Workstream P and Workstream R may proceed in parallel.
- They must use disjoint files except for intentionally coordinated root CMake/test
  wiring.
- Root wiring changes are integrated by one designated implementer task, not edited
  concurrently.
- Workstream C1 may begin after the provider is available and the existing one-shot
  Runtime path is green.
- Workstream C2 requires Runtime multi-invocation closure.

This separates the first production end-to-end proof from the later bounded multi-cycle
Agent, reducing integration risk.

---

# 8. Workstream B — Repository Engineering Baseline

## B0. Baseline inventory and preservation

**Objective:** Establish exactly what belongs in the source repository before any
cleanup or initial commit.

**Tasks:**

- classify source, authority documents, historical reports, reference files, generated
  build directories, and temporary artifacts;
- identify files that must remain local but untracked;
- inspect root CMake damage without changing architecture;
- record the Ubuntu toolchain and dependency gap;
- define the initial commit content;
- preserve all user-authored material until explicitly classified.

**Acceptance:**

- no source or authority artifact is deleted without an explicit disposition;
- generated artifacts are clearly distinguished from source;
- the proposed initial baseline file set is reviewable.

## B1. CMake and repository hygiene repair

**Objective:** Restore a correct, portable top-level build graph.

**Tasks:**

- repair missing CMake variable expansions and install paths;
- make prototype existence checks repository-relative;
- preserve current target boundaries and warning policy;
- update `.gitignore` for all generated build directory patterns;
- ensure no build artifact is required for a clean build;
- keep install support either demonstrably working or explicitly disabled with
  accurate documentation.

**Acceptance:**

- configure succeeds from a new out-of-tree directory;
- all expected production and test targets appear;
- prototype options behave deterministically;
- install/export configuration has a passing smoke test when enabled;
- no generated build directory is included in the baseline.

## B2. Ubuntu dependency and build bootstrap

**Objective:** Make clean Ubuntu setup reproducible.

**Tasks:**

- define required package versions or minimum versions;
- install dependencies only after Owner authorization;
- document setup commands;
- choose Make or Ninja as the primary local generator;
- configure and build Debug with GCC;
- add a Clang build after the GCC baseline is green.

**Acceptance:**

- a clean Ubuntu environment can follow documented commands;
- no undeclared local path or pre-existing build directory is required;
- compiler warnings remain errors.

## B3. Test and CI baseline

**Objective:** Convert historical test claims into reproducible current evidence.

**Tasks:**

- run complete CTest from a clean build;
- inventory test targets and test case counts;
- enable GitHub Actions for Ubuntu GCC build/test;
- add Clang or sanitizer coverage as a later matrix entry after baseline stability;
- ensure CI uses the same supported CMake path as local development.

**Acceptance:**

- all repository tests pass from a clean build;
- CI contains executable workflow logic;
- failure logs are retained and actionable;
- no live model credential is required by baseline CI.

## B4. Documentation and Git baseline

**Objective:** Create a trustworthy development starting point.

**Tasks:**

- update README to reflect the actual project phase and build instructions;
- update the documentation index with authority/current/historical categories;
- mark superseded status documents clearly;
- record verified Ubuntu baseline results;
- prepare the first Git commit after Project Lead and independent review.

**Acceptance:**

- `git status` is clean after the approved baseline commit;
- README claims match source and test evidence;
- a new contributor can find current architecture, build, test, and roadmap documents;
- the initial commit contains no generated artifacts or secrets.

**Workstream B closure gate:** Independent review PASS and Project Lead acceptance.

---

# 9. Workstream P — Production Model Provider

## P0. Provider governance re-baselining

**Objective:** Reconcile the frozen OpenAI-compatible protocol with the Ubuntu
environment and remove obsolete WinHTTP implementation assumptions.

**Required Owner decision:**

- remote OpenAI-compatible endpoint; or
- local OpenAI-compatible backend on Ubuntu.

**Tasks:**

- verify selected backend reachability and model availability without exposing secrets;
- revise the implementation plan for Ubuntu;
- select the HTTP transport and JSON strategy;
- define dependency provenance and installation method;
- define timeout, TLS, endpoint, credential, and model configuration semantics;
- define live-test gating.

**Recommended technical direction:**

- retain OpenAI-compatible HTTP as the provider protocol;
- use a maintained Linux-capable HTTP implementation rather than a hand-written client;
- use a maintained JSON parser rather than a long-term hand-written JSON grammar;
- isolate both behind the provider implementation;
- expose only provider configuration and `ak::model::Model` semantics.

**Acceptance:**

- backend selection and environment prerequisites are explicit;
- WinHTTP-only assumptions are removed or conditionally isolated;
- dependency choices receive independent review;
- Phase 1 implementation is explicitly authorized by the Owner.

## P1. Provider contract-preserving implementation

**Objective:** Implement one production provider behind `ak::model::Model`.

**Minimum behavior:**

- provider identity and lifecycle;
- immutable `ModelInput` consumption;
- synchronous inference;
- response conversion to `ModelResult`;
- provider-neutral failure categories;
- deterministic invalid-response handling;
- timeout and transport failure mapping;
- secret-safe diagnostics;
- clean shutdown of provider-owned resources.

**Protected boundaries:**

- provider does not produce `ModelAction`;
- provider does not access Agent, Runtime, Tool, Planner, Memory, or Context;
- transport/JSON types do not cross provider public headers;
- existing Model and AgentModel contracts remain source-compatible unless a separately
  reviewed defect requires change.

## P2. Provider verification

**Required tests:**

- configuration validation;
- lifecycle transition matrix;
- request conversion;
- successful response conversion;
- malformed/empty response;
- HTTP and transport failures;
- timeout;
- authentication/authorization failure classification;
- provider unavailable behavior;
- secret redaction;
- AgentModelHost/Binding integration;
- boundary/static dependency checks;
- opt-in real endpoint inference.

**Acceptance:**

- deterministic tests run without network access;
- live inference is separately gated and produces real provider evidence;
- no failed inference is represented as success;
- baseline tests remain green;
- independent review PASS.

**Workstream P closure gate:** Real provider evidence, independent review PASS, Project
Lead acceptance.

---

# 10. Workstream R — Runtime Multi-Invocation

## R0. Contract and lifecycle decision

**Objective:** Define reusable Runtime semantics before implementation.

**Recommended lifecycle model:**

```text
Runtime service lifecycle:
    Created -> Ready -> Stopped/Failed

Per-Session execution lifecycle:
    Accepted -> Running -> Completed/Failed/Cancelled

Runtime may execute multiple Sessions sequentially while Ready.
```

The final contract must decide:

- whether `Run(Session&)` implicitly starts Runtime or requires explicit `Start()`;
- legal calls before start, during execution, after stop, and after failure;
- which state is reset per invocation;
- whether capability registrations and EventBus subscribers persist;
- how invocation result retention is bounded;
- duplicate `request_id` behavior;
- failure isolation between Sessions;
- thread-safety and concurrent `Run` policy;
- Stop and cancellation semantics;
- compatibility behavior for existing callers.

**Initial scope recommendation:** Sequential multi-invocation only. Concurrent `Run`
calls remain rejected until separately governed.

**Acceptance:**

- contract is explicit enough to test every legal/illegal transition;
- current one-shot behavior is either preserved through compatibility methods or
  intentionally migrated with documented impact;
- independent contract review PASS before code changes.

## R1. Runtime implementation

**Objective:** Execute multiple sequential Sessions/invocations through one Runtime
service instance.

**Implementation constraints:**

- preserve Runtime ownership of Scheduler, Executor, Resolver, EventBus, and lifecycle;
- reset only invocation-scoped state;
- preserve service-scoped capability registrations;
- prevent result cross-talk between request IDs;
- avoid a broad `Reset()` with unspecified semantics;
- do not introduce Agent dependencies into Runtime;
- do not add concurrency as an accidental side effect.

## R2. Runtime verification

**Required scenarios:**

- two successful invocations on one Runtime;
- tool invocation followed by completion;
- two different capabilities;
- duplicate and distinct request IDs;
- first invocation failure followed by a valid second invocation;
- missing capability followed by valid capability;
- result isolation and retention policy;
- EventBus event order across Sessions;
- Stop behavior;
- illegal concurrent/re-entrant invocation;
- existing walking skeleton and Runtime tests;
- RuntimePublicApiAdapter repeated submission.

**Acceptance:**

- repeated sequential invocation is deterministic;
- one failed invocation does not poison later valid work unless the contract defines a
  terminal Runtime failure;
- no invocation result cross-talk;
- existing public-boundary isolation remains intact;
- independent review PASS.

**Workstream R closure gate:** Contract accepted, implementation verified, independent
review PASS, Project Lead acceptance.

---

# 11. Workstream C — Production Composition

## C0. Composition contract

**Objective:** Define one production composition root without creating a framework.

The contract shall specify:

- owned roots and injected dependencies;
- initialization and shutdown order;
- objective and input entry surface;
- configuration ownership;
- Model provider binding;
- capability registration/bootstrap;
- Context and Memory initialization;
- bounded execution policy;
- completion and failure outcome;
- diagnostics and correlation identifiers;
- test seams that remain permitted;
- FWA compatibility/migration strategy.

**Non-goal:** A general-purpose DI container, plugin manager, provider registry, or
application framework.

## C1. Minimal production bootstrap

**Dependency:** Workstream P closed; existing one-shot Runtime path green.

**Objective:** Prove one production end-to-end execution without test wiring.

**Minimum path:**

```text
CLI/configuration
  -> production composition root
  -> Prompt
  -> production Model provider
  -> ModelResult
  -> Agent interpretation
  -> optional single Runtime capability invocation
  -> RuntimeObservation
  -> Context update
  -> deterministic terminal result
```

**Deliverables:**

- production composition library;
- minimal executable or example;
- safe environment-based configuration;
- one harmless production-representative capability;
- integration test using deterministic transport/capability seams;
- separately gated live model smoke test.

**Acceptance:**

- executable target is built from production sources;
- no test header or test-only Model/Tool executor is linked;
- completion, invalid result, model failure, capability failure, and success paths are
  observable;
- clean shutdown occurs on every terminal path;
- independent review PASS.

## C2. Unified bounded Agent path

**Dependency:** Workstreams P and R closed, C1 closed.

**Objective:** Converge FWA loop semantics and Runtime-backed production boundaries.

**Target path:**

```text
Objective
  -> Context + Memory + Planner + Tool capability material
  -> Prompt
  -> production Model
  -> ModelResult
  -> Agent-owned ModelAction
  -> Runtime-backed execution when requested
  -> RuntimeObservation
  -> Context update
  -> completion evaluation
  -> next bounded cycle or terminal stop
```

**Required policies:**

- configurable hard `max_cycles`;
- no unbounded loop;
- no implicit retry;
- every cycle has a stable cycle ID;
- every Runtime request has a stable request ID;
- a terminal Model failure stops the loop;
- invalid Model output is not converted to tool execution;
- Runtime failure is visible to Agent policy and Context according to contract;
- completion evaluation is Agent-owned;
- FWA test seams are removed from the production route.

## C3. FWA disposition

After C2 is accepted, the Project Lead shall propose one of:

1. adapt FWA tests to exercise the unified production composition with deterministic
   dependencies; or
2. retain FWA as an explicitly historical/minimal example while production tests use
   the unified path.

Two independently evolving production Agent paths are not acceptable.

**Workstream C closure gate:** Production executable evidence, bounded multi-cycle
evidence, independent review PASS, Project Lead acceptance.

---

# 12. Cross-Cutting Requirements

## 12.1 Security

- credentials only through approved runtime configuration;
- no credential values in source, tests, logs, reports, or diagnostics;
- HTTPS verification enabled for remote endpoints;
- tool capabilities are allowlisted;
- tool arguments and model output are treated as untrusted input;
- no shell execution is introduced without a separate contract and security review.

## 12.2 Error handling

- no silent fallback to success;
- no broad catch that loses the failure category;
- provider, Agent, and Runtime failure domains remain distinguishable;
- human-readable diagnostics supplement, but do not replace, structured status.

## 12.3 Portability

- Ubuntu/GCC is the primary program baseline;
- Clang is the secondary Linux compiler;
- Windows compatibility is preserved where practical but cannot force Linux code to use
  Windows-only transport;
- platform-specific code stays behind private implementation boundaries.

## 12.4 Observability

The program shall progressively establish structured correlation for:

```text
objective_id
cycle_id
model request
runtime request_id
session_id
workflow_id
task_id
capability_id
terminal status
failure category
```

Diagnostics strings shall not be parsed as the long-term control protocol.

## 12.5 Documentation

Every task updates only directly affected documentation. Current-state documents must
state:

- what is implemented;
- what is verified;
- what remains absent;
- what is historical;
- which environment produced the evidence.

---

# 13. Prompt Contract

The Project Lead will issue a separate prompt for every implementation and review task.

## 13.1 Implementation prompt structure

Each OpenCode + DeepSeek prompt shall contain:

1. **Role:** implementation owner for the named task.
2. **Repository and environment:** exact workspace and platform.
3. **Authority:** documents and source files that govern the task.
4. **Objective:** one measurable outcome.
5. **In scope:** explicit files/behaviors.
6. **Out of scope:** protected surfaces and forbidden expansion.
7. **Required investigation:** repository evidence to read before editing.
8. **Implementation requirements:** behavior and boundaries.
9. **Test requirements:** exact minimum validation.
10. **Deliverables:** code, tests, documentation, and report.
11. **Stop conditions:** ambiguity, missing authorization, dependency/credential need,
    conflicting user changes, or architecture impact.
12. **Completion format:** changed files, commands, results, residuals, and traceability.

The prompt must tell the implementer to perform the work, not merely propose it.

## 13.2 Independent review prompt structure

Each TRAE + GLM-5.2 prompt shall contain:

1. **Role:** independent read-only reviewer.
2. **Artifact under review:** exact working-tree revision or diff.
3. **Authority and acceptance criteria.**
4. **Required review dimensions:**
   - functional correctness;
   - boundary/ownership compliance;
   - failure semantics;
   - test quality;
   - regression risk;
   - Linux portability;
   - security where relevant;
   - documentation truthfulness.
5. **Required reproduction:** commands or evidence to independently check.
6. **Forbidden behavior:** no implementation changes and no trust in author claims.
7. **Finding format:** ID, severity, location, evidence, impact, required correction.
8. **Verdict:** PASS, PASS WITH OBSERVATIONS, or FAIL.

## 13.3 Correction prompt structure

Correction prompts shall:

- quote stable finding IDs;
- require root-cause correction;
- prohibit unrelated cleanup;
- require regression tests for behavioral defects;
- require an updated evidence report;
- return to the same reviewer for closure when possible.

---

# 14. Milestones

| Milestone | Outcome | Dependencies | Exit gate |
|---|---|---|---|
| M0 | Program plan accepted | None | Owner acceptance |
| M1 | Ubuntu repository baseline | M0 | Workstream B PASS |
| M2-P | Production provider ready | M1 + backend decision | Workstream P PASS |
| M2-R | Runtime multi-invocation ready | M1 | Workstream R PASS |
| M3 | Minimal production Agent executable | M2-P | C1 PASS |
| M4 | Unified bounded production Agent | M2-P + M2-R + M3 | C2/C3 PASS |
| M5 | Production-readiness qualification | M4 | Final qualification PASS |

M2-P and M2-R are intentionally parallel after M1.

---

# 15. Final Qualification

The program is complete only when all of the following are demonstrated from a clean
Ubuntu checkout:

1. Configure, build, test, and install/package smoke test succeed.
2. CI reproduces the supported build and test path.
3. One production Model provider performs a real, opt-in inference.
4. Provider failure cannot become synthetic success.
5. One production executable runs without linking test-only code.
6. A tool request travels through the sanctioned Agent-to-Runtime adapter.
7. Runtime executes at least two sequential invocations on one service instance.
8. Invocation results and correlation IDs do not cross-talk.
9. Agent performs more than one bounded decision cycle when required.
10. Agent terminates at completion, failure, invalid output, timeout, cancellation, or
    `max_cycles`.
11. FWA and Runtime-backed behavior have a documented single production authority.
12. No secret is present in source, Git history, logs, or reports.
13. README and current-state documentation match verified behavior.
14. All Critical, Major, and Minor findings are closed or explicitly deferred by Owner.
15. Project Lead issues a final evidence-based closure recommendation.

---

# 16. Immediate Execution Queue

After Owner accepts this plan, the Project Lead shall issue tasks in this order:

1. **B0-01 — Repository Baseline Classification and Initial Commit Scope**
   - read-only inventory;
   - no deletion;
   - no commit;
   - output: exact keep/ignore/archive proposal.
2. **B1-01 — Root CMake Reconstruction and Testable Repair Plan**
   - analyze damaged variable expansions and install graph;
   - independent plan review before editing.
3. **B1-02 — CMake and `.gitignore` Implementation**
   - implement only after B1-01 acceptance.
4. **B2-01 — Ubuntu Toolchain Preparation**
   - requires Owner approval before package installation.
5. **B3-01 — Clean GCC Build and Full CTest Baseline**
6. **B3-02 — Ubuntu CI Activation**
7. **B4-01 — README, Documentation Index, and Initial Git Baseline**
8. Launch **P0-01 Provider Backend Decision Preparation** and
   **R0-01 Runtime Multi-Invocation Contract** in parallel.

No Provider implementation or Runtime lifecycle code change starts before Workstream B
is closed.

---

# 17. Program Decision Record

The program adopts the following initial decisions:

```text
D-001  Ubuntu is the primary engineering baseline.
D-002  Repository baseline precedes feature implementation.
D-003  Provider and Runtime multi-invocation proceed in parallel after baseline.
D-004  OpenAI-compatible HTTP remains the provider protocol unless Owner changes it.
D-005  Backend selection remains an Owner decision.
D-006  Production Composition is delivered in two stages:
       minimal production bootstrap, then unified bounded Agent.
D-007  Sequential Runtime multi-invocation precedes concurrent Runtime execution.
D-008  Existing Agent/Model/Runtime ownership boundaries remain protected.
D-009  No unbounded Agent loop is permitted.
D-010  Implementation and independent review remain separate responsibilities.
D-011  Evidence, not document status wording, determines closure.
D-012  One unified production Agent path is the final integration target.
```

---

# 18. Approval

Owner approval of this document means:

- the four-workstream scope and sequencing are accepted as the working baseline;
- the Project Lead may prepare and issue the B0-01 read-only task prompt;
- implementation, dependency installation, backend selection, credentials, live
  endpoint use, and Git commit creation still require their task-specific gates.

Approval does not waive independent review or authorize all program changes at once.

