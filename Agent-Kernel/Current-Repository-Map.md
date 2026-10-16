# Current Repository Map

## 1. Document Identity

```text
Document:  Current Repository Map
Purpose:   Accurate repository map for Agent Runtime Integration (TASK 0.2)
Status:    INFORMATIONAL / EVIDENCE ONLY
Authority: NOT an architecture document
           NOT a design document
           NOT a refactoring plan
```

All paths, targets, and statuses below were verified against the current
repository (2026-08-19). This document does not modify anything.

---

## 2. Repository Tree (Runtime Integration relevant)

```text
agent-kernel/
├── CMakeLists.txt                     # root: C++20, /W4 /WX, options, add_subdirectory(src|runtime|tests|examples|prototype)
├── include/
│   └── agent_kernel/
│       ├── object_id.hpp              # legacy kernel root identities (SessionID/TaskID/WorkflowID)
│       ├── session.hpp                # legacy Session object model (C Runtime input)
│       ├── workflow.hpp               # legacy Workflow object model
│       ├── task.hpp                   # legacy Task object model
│       ├── state.hpp / relationship.hpp
│       ├── agent/                     # P1-IS002 Agent (+ coordination/, execution/, runtime/)
│       ├── agent_planner/             # P1-IS005 Agent-facing Planner
│       ├── agent_prompt/              # P1-IS007 Agent-facing Prompt
│       ├── agent_tool/                # P1-IS006 Agent-facing Tool
│       ├── agent_model/               # P1-IS008 Agent-facing Model
│       ├── memory/                    # P1-IS003
│       ├── context/                   # P1-IS004
│       ├── planner/                   # P1-IS005
│       ├── prompt/                    # P1-IS007
│       ├── model/                     # P1-IS008
│       ├── tool/                      # P1-IS006
│       ├── foundation/                # P1-IS001
│       ├── fwa/                       # First Working Agent public surface
│       ├── runtime/                   # capability/ (ICapabilityResolver, ExecutionBinding)
│       ├── scheduler/                 # i_scheduler.hpp, scheduling_policy.hpp
│       ├── executor/                  # i_executor.hpp, execution_*.hpp
│       ├── session/                   # session_builder.hpp, workflow_registry.hpp
│       ├── workflow/                  # workflow_graph.hpp, task_registry.hpp, graph_*
│       └── task/                      # task_*.hpp, task_execution_descriptor.hpp
├── src/
│   ├── CMakeLists.txt                 # agent_kernel (legacy kernel model) + subsystem subdirectories
│   ├── state.cpp, object_id.cpp, graph_*.cpp, workflow*.cpp, task*.cpp, session*.cpp
│   ├── agent/                         # agent_kernel_agent (+ composition/ for FWA target)
│   ├── agent/composition/             # agent_kernel_first_working_agent
│   ├── agent_model/ agent_planner/ agent_prompt/ agent_tool/
│   ├── memory/ context/ planner/ prompt/ model/ tool/
│   └── foundation/                    # agent_kernel_foundation
├── runtime/                           # C Runtime (Runtime Revision 2, P0R0001–0006)
│   ├── CMakeLists.txt                 # agent_kernel_runtime (+ walking_skeleton_demo)
│   ├── include/*.h                    # runtime.h, scheduler, executor, capability_resolver, event_bus, lifecycle, state_machine, configuration
│   ├── src/*.cpp
│   ├── tests/                         # runtime_test (126 tests, 8 suites)
│   └── demo/walking_skeleton_demo.cpp
├── tests/
│   ├── CMakeLists.txt                 # subsystem test subdirectories + first_working_agent
│   ├── agent/ memory/ context/ planner/ agent_planner/ tool/ agent_tool/ prompt/ agent_prompt/ model/ agent_model/ foundation/
│   ├── first_working_agent/
│   └── integration/ regression/ unit/ benchmark/        # placeholders (.gitkeep only)
├── prototype/ avp0000 avp0001         # out of Runtime Integration scope
├── validation/ p0r0007_validation_driver
└── examples/
```

---

## 3. Component Map

| Component | Repository Location | Implementation Status | Public Boundary | Notes |
|---|---|---|---|---|
| Agent | `include/agent_kernel/agent/`, `src/agent/agent.cpp` | Implemented | `ak::agent::Agent` (+ `AgentPlannerHost`, `AgentPromptHost`, `AgentToolBinding`, `RuntimeInteractionPort`) | Runtime port is contract-only |
| Memory | `include/agent_kernel/memory/`, `src/memory/` | Implemented | `ak::memory::Memory`, `MemoryAgentContract` | No Runtime binding |
| Context | `include/agent_kernel/context/`, `src/context/` | Implemented | `ak::context::Context`, `ContextAgentContract::Update()` | String-object content |
| Planner | `include/agent_kernel/planner/`, `src/planner/` | Implemented | `ak::planner::Planner`, `AgentPlannerBinding` | Plan payload → Prompt |
| Prompt | `include/agent_kernel/prompt/`, `src/prompt/` | Implemented | `ak::prompt::Prompt*`, `AgentPromptHost` | Assembles model-facing material |
| Model | `include/agent_kernel/model/`, `src/model/` | Implemented (P1-IS008) | `ak::model::Model`, `ModelInput`, `ModelResult`, `AgentModelBinding/Host` | Not linked into FWA |
| Tool | `include/agent_kernel/tool/`, `src/tool/` | Implemented (discovery + preparation) | `ak::tool::Tool`, `AgentToolBinding`, `IToolProvider` | Execution not implemented |
| Runtime (C) | `runtime/` | Implemented (P0R0001–0006) | `ak::runtime::Runtime` facade + component headers | 126 tests + WalkingSkeletonDemo |
| Runtime capability contract | `include/agent_kernel/runtime/capability/` | Implemented (interface layer) | `ICapabilityResolver`, `ExecutionBinding` | Legacy AK0023-era surface |
| RuntimeInteractionPort | `include/agent_kernel/agent/runtime/runtime_interaction_port.hpp` | Contract-only (P1-IS002 Phase 1) | `RuntimePublicApiBoundary()` marker | Phase 5 deferred |
| FWA | `include/agent_kernel/fwa/`, `src/agent/composition/` | Implemented (accepted) | `FirstWorkingAgentComposition`, `ModelAction`, `ModelBoundary`, `ToolExecutionBoundary` | No Runtime link |

---

## 4. Runtime Map

| Element | Location | Status |
|---|---|---|
| Runtime core | `runtime/include/runtime.h` (`ak::runtime::Runtime`) | Implemented |
| Public API facade | `Runtime::Run(ak::Session&)`, `Stop()`, component accessors | Implemented (standalone) |
| Session | `include/agent_kernel/session.hpp`, `session/session_builder.hpp` | Implemented (legacy object model) |
| Workflow | `include/agent_kernel/workflow.hpp`, `workflow/` | Implemented (legacy object model) |
| Task | `include/agent_kernel/task.hpp`, `task/` | Implemented (legacy object model) |
| Scheduler | `runtime/include/runtime_scheduler.h`, `include/agent_kernel/scheduler/i_scheduler.hpp` | Implemented (C runtime) / interface |
| Executor | `runtime/include/runtime_executor.h`, `include/agent_kernel/executor/i_executor.hpp` | Implemented (C runtime) / interface |
| Event Bus | `runtime/include/event_bus.h` | Implemented (C runtime) |
| Capability Resolver | `runtime/include/capability_resolver.h`, `include/agent_kernel/runtime/capability/i_capability_resolver.hpp` | Implemented (C runtime) / interface |
| RuntimeInteractionPort | `include/agent_kernel/agent/runtime/runtime_interaction_port.hpp` | Contract-only |
| Agent → Runtime binding | — | Integration missing (no target links `agent_kernel_runtime` into Agent/FWA) |

---

## 5. Agent Map

| Aspect | Location / Status |
|---|---|
| Agent public API | `include/agent_kernel/agent/agent.hpp` (`Initialize`, `BeginCoordination`, `AcceptObjective`, `EvaluateObjective`, `FindObjective`, `Diagnostics`, `RuntimePort()`) |
| Agent ownership | Agent owns intelligent execution; no Runtime internals (isolation tests PASS) |
| Planner connection | `AgentPlannerHost/Binding` — implemented; exercised by FWA and planner integration tests |
| Prompt connection | `AgentPromptHost/Binding` — implemented; exercised by FWA |
| Model connection | `AgentModelBinding/Host` — implemented (P1-IS008); FWA uses its own `ModelBoundary` seam instead |
| Tool connection | `AgentToolBinding` — implemented (discovery + preparation); FWA uses it |
| Context connection | `ContextAgentContract` — implemented; FWA updates Context per cycle |
| Memory connection | `MemoryAgentContract` — implemented; FWA exercises lifecycle + material |
| FWA connection | `FirstWorkingAgentComposition` drives Agent via public APIs only |

---

## 6. FWA Map

| Aspect | Location / Status |
|---|---|
| FWA public headers | `include/agent_kernel/fwa/model_action.hpp`, `first_working_agent_configuration.hpp`, `first_working_agent_composition.hpp` |
| FWA implementation | `src/agent/composition/first_working_agent_composition.cpp` |
| FWA target | `agent_kernel_first_working_agent` (links agent, agent_planner, agent_tool, agent_prompt, tool, context, memory, foundation; NO model, NO runtime) |
| FWA tests | `tests/first_working_agent/` (13 tests + boundary check) |
| FWA model boundary | `ModelBoundary = std::function<ModelAction(const PromptResult&)>` (ModelAction-direct) |
| FWA tool path | `AgentToolBinding` discover/get/prepare → `ToolExecutionBoundary` test seam |
| FWA context update | `ContextAgentContract::Update()` with `"[tool-result] ..."` string |
| FWA execution loop | `StepCycle()` / `Run()` with `max_cycles` (default 8) |

---

## 7. Test Map

| Directory | Test target | CTest name | Covers |
|---|---|---|---|
| `tests/agent/` | `agent_test` | AgentTest, AgentBoundaryCheck | Agent lifecycle/coordination + runtime isolation |
| `tests/memory/` | `memory_test` | MemoryTest, MemoryBoundaryCheck | Memory |
| `tests/context/` | `context_test` | ContextTest, ContextBoundaryCheck | Context |
| `tests/planner/` | `planner_test`, `planner_integration_test` | PlannerTest, PlannerIntegrationTest, AgentPlannerTest, AgentPlannerBoundaryCheck | Planner + AgentPlanner |
| `tests/agent_planner/` | `agent_planner_test` | (see above) | Agent–Planner |
| `tests/tool/` | `agent_kernel_tool_tests` | ToolTest, ToolBoundaryCheck | Tool |
| `tests/agent_tool/` | `agent_kernel_agent_tool_tests` | AgentToolTest, AgentToolBoundaryCheck | Agent–Tool |
| `tests/prompt/` | `agent_kernel_prompt_tests` | PromptTest, PromptBoundaryCheck | Prompt |
| `tests/agent_prompt/` | `agent_kernel_agent_prompt_tests` | AgentPromptTest, AgentPromptBoundaryCheck | Agent–Prompt |
| `tests/model/` | `agent_kernel_model_tests` | ModelTest, ModelBoundaryCheck | Model (P1-IS008) |
| `tests/agent_model/` | `agent_kernel_agent_model_tests` | AgentModelTest, AgentModelBoundaryCheck | Agent–Model (ModelResult path) |
| `tests/foundation/` | `foundation_test` | FoundationTest, FoundationBoundaryCheck | Foundation |
| `tests/first_working_agent/` | `first_working_agent_integration_test` | FirstWorkingAgentTest, FirstWorkingAgentBoundaryCheck | FWA loop |
| `runtime/tests/` | `runtime_test` | RuntimeTest | C Runtime (126 tests) |
| `runtime/demo/` | `walking_skeleton_demo` | WalkingSkeletonDemo | C Runtime E2E |
| `tests/integration|regression|unit|benchmark/` | — | — | placeholders only |

---

## 8. Build Map

- Root `CMakeLists.txt`: C++20, `/W4 /WX /utf-8 /MP` (MSVC), options `AK_BUILD_TESTS/EXAMPLES/PROTOTYPE/ENABLE_INSTALL`; `add_subdirectory(src)`, `add_subdirectory(runtime)`, `add_subdirectory(tests)`.
- `src/CMakeLists.txt`: `agent_kernel` (legacy kernel model, links `agent_kernel_foundation`) + 12 subsystem subdirectories.
- `tests/CMakeLists.txt`: registers all subsystem test subdirectories + `first_working_agent`.
- Production targets: `agent_kernel`, `agent_kernel_foundation`, `agent_kernel_agent`, `agent_kernel_agent_planner`, `agent_kernel_agent_prompt`, `agent_kernel_agent_tool`, `agent_kernel_agent_model`, `agent_kernel_planner`, `agent_kernel_prompt`, `agent_kernel_model`, `agent_kernel_tool`, `agent_kernel_context`, `agent_kernel_memory`, `agent_kernel_first_working_agent`, `agent_kernel_runtime`.
- Test targets: listed in §7; plus `walking_skeleton_demo`, `avp0000_*`, `avp0001_*`, `p0r0007_validation_driver`.
- No CMake file is modified by this task.

---

## 9. Dependency Direction (actual)

```text
Agent layer → subsystem hosts/bindings (Planner, Prompt, Tool, Model, Context, Memory)     — existing links
FWA (agent_kernel_first_working_agent) → agent, planner, prompt, tool, context, memory, foundation  — existing links
agent_kernel_runtime → agent_kernel (legacy model) + foundation                            — existing link

Tool → Runtime        — does NOT exist (no Tool-to-Runtime link)
Runtime → Agent       — does NOT exist (no Agent-to-Runtime link, no Runtime link in FWA)
Agent ↔ Runtime       — does NOT exist (RuntimeInteractionPort is contract-only)
```

These are stated from actual CMake link evidence. The absent edges are
integration gaps, not drawn as existing.

---

## 10. Implemented / Contract / Gap Matrix

| Area | Existing Implementation | Existing Contract | Integration Gap | Evidence |
|---|---|---|---|---|
| Agent | Implemented | — | — | `src/agent/`, `tests/agent/` |
| Runtime Public API | C Runtime facade (`ak::runtime::Runtime`) | `RuntimeInteractionPort` (contract-only) | Agent↔Runtime binding, request translation, status observation | `runtime/runtime.h`, `runtime_interaction_port.hpp` |
| Observation | FWA string `"[tool-result] ..."` in Context (test path) | none | Unified observation representation | `deterministic_test_executor.hpp`, FWA tests |
| Context update | FWA test path (`ContextAgentContract::Update`) | `ContextAgentContract` | Runtime-result → Context wiring | `context_agent_contract.hpp` |
| Repeated / long-running execution | Bounded FWA loop (`max_cycles`) | none | Continuous/runtime-mediated loop, lifecycle, cancellation | FWA `Run()`/`StepCycle()` |
| Cancellation | C Runtime `Runtime::Stop()` / `kCancelled` | none at Agent level | Agent-level cancellation semantics | `runtime/runtime.h` |
| Failure / recovery | ModelResult failure (P1-IS008), FWA deterministic failures | — | Runtime-level failure/recovery in Agent loop | `model/model_result.hpp`, FWA tests |

---

## 11. Closed Authority Protection

The following are CLOSED authority and were not modified by this task:

```text
AK0039–AK0046
P1-IS001–P1-IS008
First Working Agent (Sprint + TASK 2–8 evidence)
```

No apparent inconsistency was resolved here. Any apparent inconsistency that a
future task finds shall be recorded as a Reconciliation Item, not resolved
without architecture governance.

---

## 12. Map Self-Check

- [x] Actual paths verified (tree from `Get-ChildItem`)
- [x] Actual source files verified (per-subsystem inventory)
- [x] Actual tests verified (test executables + CTest names)
- [x] Actual CMake targets verified (all `add_library`/`add_executable` scanned)
- [x] Runtime components verified (C Runtime + capability interface layer)
- [x] Agent components verified (agent + hosts/bindings + RuntimeInteractionPort)
- [x] FWA location verified (`fwa/` + `src/agent/composition/`)
- [x] Dependency direction verified (link sets; absent edges marked absent)
- [x] Implemented vs contract-only distinguished (RuntimeInteractionPort contract-only)
- [x] Integration gaps distinguished (Implemented/Contract/Gap matrix)