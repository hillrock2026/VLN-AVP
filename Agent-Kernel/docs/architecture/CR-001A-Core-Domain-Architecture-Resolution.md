# CR-001A ‚Ä?Core Domain Architecture Resolution

**Status:** Architecture Decision Record  
**Version:** 1.0  
**Phase:** AVP-1 Core Foundation Prototype  

---

## Document Status

| Field | Value |
|-------|-------|
| Status | Architecture Decision Record |
| Version | 1.0 |
| Reviewed Components | AK0011, AK0012, AK0013, AK0014, AK0015, AK0016 |
| Objective | Stabilize Core Domain Model before Runtime development |

---

## 1. Resolution Summary

The following six architecture decisions are approved and now constitute the authoritative interpretation of the Core Domain Model.

| # | Decision | Status | Affected Components |
|---|----------|--------|---------------------|
| 1 | Task is a structural execution description, NOT an executable object | Approved | AK0011 ¬ß3.4, AK0016 |
| 2 | Execution binding is separated from Task | Approved | AK0016, task.hpp, TaskExecutionDescriptor (new) |
| 3 | KernelObjectState is unified with per-object lifecycle permissions | Approved | AK0012, state.hpp |
| 4 | WorkflowGraph is the single source of truth for dependency topology | Approved | AK0013 |
| 5 | TaskDependency is descriptive metadata, not the authoritative graph | Approved | AK0016, task_dependency.hpp |
| 6 | KernelHandle remains reserved foundation infrastructure | Approved | AK0012, kernel_handle.hpp |

---

## 2. CR-001-01 / CR-001-02 ‚Ä?Task Execution Semantic Resolution

### 2.1 Problem

Previous specifications contained inconsistent interpretations of Task:

| Aspect | Old Interpretation | New Architecture |
|--------|-------------------|------------------|
| Task role | Task owns executable behavior | Task describes execution intent |
| Execution mechanism | callable/function, Execute() | No execution mechanism in Task |
| Executor relationship | Executor invokes Task directly | Executor resolves capability through Runtime |
| Task capabilities | Hardcoded tool/function references | Capability name resolved at Runtime |

### 2.2 Decision

**Task owns:**

| Owned Element | Type | Purpose |
|---------------|------|---------|
| Task identity | `TaskID` (via TypedKernelObject) | Stable identification |
| Task metadata | `KernelMetadata` | Human-readable description |
| Task lifecycle state | `KernelObjectState` | Current lifecycle phase |
| Task dependency description | `vector<TaskDependency>` | Upstream TaskIDs + dependency kind |
| Input/output contract | `TaskContract` | What data is expected and produced |
| Execution requirement description | `TaskExecutionDescriptor` | What capability is needed |

**Task does NOT own:**

| Excluded Element | Reason |
|------------------|--------|
| function pointer | Runtime mechanism, not structural |
| callable / lambda | Runtime mechanism, not structural |
| callback | Runtime mechanism, not structural |
| thread | Executor concern |
| executor | AK0030+ concern |
| tool instance | Plugin/Runtime concern |
| plugin instance | Plugin/Runtime concern |

### 2.3 New Concept: TaskExecutionDescriptor

**File:** `include/agent_kernel/task/task_execution_descriptor.hpp`

**Purpose:** Describe WHAT capability is required. Not HOW execution happens.

**Structure:**

```
TaskExecutionDescriptor
  ‚îú‚îÄ‚îÄ capability (ExecutionCapability)
  ‚î?    ‚îú‚îÄ‚îÄ name: string           (e.g., "llm.chat", "code.execute")
  ‚î?    ‚îú‚îÄ‚îÄ versionConstraint: string  (e.g., ">=1.0,<2.0")
  ‚î?    ‚îî‚îÄ‚îÄ description: string
  ‚îú‚îÄ‚îÄ hints: vector<pair<string,string>>   (advisory, non-semantic)
  ‚îî‚îÄ‚îÄ version: uint32_t
```

**Resolution flow:**

```
Task.TaskExecutionDescriptor
    |
    v
Runtime capability registry (future AK0030+)
    |
    ‚îú‚îÄ‚îÄ Resolves "llm.chat" ‚Ü?LLM plugin instance
    ‚îú‚îÄ‚îÄ Resolves "code.execute" ‚Ü?sandbox executor
    ‚îú‚îÄ‚îÄ Resolves "http.request" ‚Ü?HTTP client
    ‚îî‚îÄ‚îÄ Resolves "transform.json" ‚Ü?data transform function
    |
    v
Executor receives resolved capability + Task
    |
    v
Executor performs execution using the resolved capability
```

### 2.4 Updated Task Construction

```cpp
auto task = TaskBuilder()
    .WithID(TaskID::Generate())
    .WithParentWorkflow(workflowId)
    .WithName("GenerateResponse")
    .WithContract(inputOutputContract)
    .WithExecutionDescriptor(TaskExecutionDescriptor{
        .capability = {"llm.chat", ">=2.0", "Chat completion"},
        .hints = {{"temperature", "0.7"}, {"maxTokens", "2048"}},
    })
    .Build();
```

> **Revision 2 Note:** `Workflow::AddTask(const TaskExecutionDescriptor&)` is now the primary Core-authorized Task construction path for descriptor initialization. `TaskBuilder` remains an optional construction helper. See AK0015 Revision 2 and AK0016 Revision 2.

### 2.5 Impact on AK0016

| File | Change |
|------|--------|
| `task/task_execution_descriptor.hpp` | **New** ‚Ä?defines ExecutionCapability + TaskExecutionDescriptor |
| `task.hpp` | **Updated** ‚Ä?composes TaskExecutionDescriptor; adds `GetExecutionDescriptor()` (setter removed) |
| `task/task_builder.hpp` | **Updated** ‚Ä?adds `WithExecutionDescriptor()` |
| `docs/architecture/AK0016-Task-Specification.md` | **Updated** ‚Ä?Chapter 4 adds TaskExecutionDescriptor section |

---

## 3. CR-001-03 ‚Ä?KernelObjectState Resolution

### 3.1 Decision

`KernelObjectState` remains unified across all Kernel Objects (Session, Workflow, Task). Object-specific lifecycle permissions are defined **separately** ‚Ä?not in the state enumeration, but in per-object lifecycle documentation.

### 3.2 Rationale

| Approach | Verdict | Reason |
|----------|---------|--------|
| Unified state enum (current) | Approved | One state machine to learn. Scheduler/Executor only need one model. |
| Per-object state enums | Rejected | Would require N state machines, N transition validators, N observer contracts. |
| State subclasses | Rejected | Inheritance hierarchy would grow with each new Kernel Object. |

### 3.3 Per-Object Lifecycle Permissions

Unified state does NOT mean every object supports every transition. Permissions are documented per-object:

| Transition | Session | Workflow | Task |
|-----------|---------|----------|------|
| Created ‚Ü?Initialized | ‚ú?Initialize() | ‚ú?Initialize() | ‚ú?Initialize() |
| Initialized ‚Ü?Ready | ‚ú?Activate() | ‚ú?Activate() | (implicit after init) |
| Ready ‚Ü?Running | (Runtime drives) | (Scheduler drives) | (Executor drives) |
| Running ‚Ü?Suspended | ‚ú?(future) | ‚ú?(future) | ‚ù?|
| Running ‚Ü?Completed | (Runtime drives) | (Scheduler drives) | (Executor drives) |
| Running ‚Ü?Failed | ‚ú?| ‚ú?| ‚ú?|
| Suspended ‚Ü?Running | ‚ú?(future) | ‚ú?(future) | ‚ù?|
| Completed ‚Ü?Destroyed | ‚ú?Destroy() | ‚ú?Destroy() | ‚ú?Destroy() |
| Failed ‚Ü?Destroyed | ‚ú?Destroy() | ‚ú?Destroy() | ‚ú?Destroy() |

No changes to `state.hpp` are required. Permissions are documented in architecture specs.

---

## 4. CR-001-04 ‚Ä?WorkflowGraph Authority Resolution

### 4.1 Decision

`WorkflowGraph` is the single source of truth for dependency topology.

### 4.2 Rationale

Task declares its local dependency view (via `TaskDependency`), but `WorkflowGraph` is the authoritative global topology. The Scheduler reads only `WorkflowGraph` to determine execution order.

### 4.3 Consistency Rule

Workflow is the single authority for dependency creation. When `Workflow::DefineDependency(from, to)` is called:

```
Workflow::DefineDependency(from, to)
  ‚îÄ‚îÄ‚Ü? WorkflowGraph::AddEdge(from, to)         (authoritative topology)
  ‚îÄ‚îÄ‚Ü? Task[to].dependencies_.push_back(from)   (synchronized via friend access)
```

**Enforcement:**
- Task has no public dependency mutation API
- `Task::AddDependency()` does NOT exist on the public interface
- Workflow controls the single dependency creation path
- WorkflowGraph is the authoritative topology source
- TaskDependency on Task is read-only metadata synchronized by Workflow

The Scheduler reads only `WorkflowGraph`. `TaskDependency` is descriptive metadata for contract analysis.

### 4.4 No changes to AK0013

`workflow_graph.hpp`, `graph_algorithms.hpp`, `graph_node.hpp`, `graph_edge.hpp` remain unchanged.

---

## 5. CR-001-05 ‚Ä?TaskDependency Role Resolution

### 5.1 Decision

`TaskDependency` is descriptive metadata, NOT the authoritative dependency graph.

### 5.2 Rationale

| Aspect | TaskDependency | WorkflowGraph |
|--------|---------------|---------------|
| Role | Local view from one Task | Global topology of all Tasks |
| Authority | Descriptive | Authoritative |
| Consumer | Contract analysis, UI display | Scheduler, Executor |
| Contains | Upstream TaskID + kind | Full edge set with traversal |
| Cycle detection | No | Yes (via GraphAlgorithms) |

### 5.3 No changes required

Both representations coexist. Their relationship is documented.

---

## 6. CR-001-06 ‚Ä?KernelHandle Resolution

### 6.1 Decision

`KernelHandle` remains reserved foundation infrastructure. It is NOT a Core Runtime contract at this phase.

### 6.2 Rationale

`KernelHandle` was introduced in AK0012 as a future-ready abstraction. It is not yet consumed by any Core Domain Object. Activation requires:

1. An object registry (to resolve handle ‚Ü?pointer)
2. A distributed execution specification (to serialize handles across processes)
3. A use case that justifies handle semantics over raw pointers

These prerequisites belong to AK0030+ (Runtime) or AK0060+ (Distributed Execution).

### 6.3 Status

`include/agent_kernel/foundation/kernel_handle.hpp` remains in the repository as reserved infrastructure. No changes required.

---

## 7. Repository Changes

### 7.1 Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| `include/agent_kernel/task/task_execution_descriptor.hpp` | **NEW** | ExecutionCapability + TaskExecutionDescriptor value types |
| `include/agent_kernel/task.hpp` | **MODIFIED** | Added `GetExecutionDescriptor()` (setter removed), `executionDescriptor_` member |
| `include/agent_kernel/task/task_builder.hpp` | **MODIFIED** | Added `WithExecutionDescriptor()` |
| `docs/architecture/CR-001A-Core-Domain-Architecture-Resolution.md` | **NEW** | This document |

### 7.2 Files Unchanged (Verified)

| File | Status |
|------|--------|
| `include/agent_kernel/foundation/kernel_handle.hpp` | ‚ú?Unchanged (reserved) |
| `include/agent_kernel/state.hpp` | ‚ú?Unchanged (unified state preserved) |
| `include/agent_kernel/workflow/workflow_graph.hpp` | ‚ú?Unchanged (single source of truth) |
| `include/agent_kernel/workflow/graph_algorithms.hpp` | ‚ú?Unchanged |
| `include/agent_kernel/task/task_contract.hpp` | ‚ú?Unchanged |
| `include/agent_kernel/task/task_dependency.hpp` | ‚ú?Unchanged (descriptive metadata) |
| `include/agent_kernel/session.hpp` | ‚ú?Unchanged |
| `include/agent_kernel/workflow.hpp` | ‚ú?Unchanged |

---

## 8. Verification

### 8.1 Acceptance Criteria

| Criterion | Status |
|-----------|--------|
| Task is structural, not executable | ‚ú?TaskExecutionDescriptor added; no function pointers/callables |
| Execution binding separated from Task | ‚ú?Descriptor names capability; Runtime resolves it |
| KernelObjectState unified | ‚ú?state.hpp unchanged; permissions documented per-object |
| WorkflowGraph is single authority | ‚ú?graph files unchanged |
| TaskDependency is descriptive | ‚ú?task_dependency.hpp unchanged; role documented |
| KernelHandle reserved | ‚ú?kernel_handle.hpp unchanged |

### 8.2 Self Review

| Check | Result |
|-------|--------|
| Did I introduce Runtime implementation? | ‚ù?No (descriptor only) |
| Did I add function pointers or callables? | ‚ù?No (capability name only) |
| Did I modify state.hpp? | ‚ù?No |
| Did I modify WorkflowGraph? | ‚ù?No |
| Did I activate KernelHandle? | ‚ù?No |
| Did I violate AK0011 ownership? | ‚ù?No |

---



---

## 9. CR-001A-R1 Resolution Notes

**Version:** 1.1  
**Objective:** Complete the unfinished corrections from CR-001A after architecture review.

### 9.1 Corrections Applied

The following corrections were applied during CR-001A-R1 implementation to align architecture documents with approved decisions:

| # | Correction | Affected Files | Rationale |
|---|------------|----------------|-----------|
| 1 | `SetExecutionDescriptor()` removed from Task public API | `task.hpp` | Descriptor is immutable after construction; set via any Core-authorized construction path (Workflow::AddTask(const TaskExecutionDescriptor&) primary, TaskBuilder optional) |
| 2 | `AddDependency()` removed from Task public API | `task.hpp` | Task cannot mutate own dependencies; Workflow::DefineDependency() is sole mutation path |
| 3 | `SetContract()` removed from Task public API | `task.hpp` | Contract set during construction only |
| 4 | `GetDependencyIDs()` removed from Task public API | `task.hpp` | Only typed `GetDependencies()` remains; WorkflowGraph is authoritative |
| 5 | `friend class Workflow` added to Task | `task.hpp` | Enables Workflow to synchronize `Task::dependencies_` when DefineDependency() is called |
| 6 | TaskBuilder `WithDependency()`/`WithDependencies()` removed | `task_builder.hpp` | Dependencies created through Workflow, not TaskBuilder |
| 7 | AK0011 Task responsibility corrected: "execution unit" ‚Ü?"execution intent" | `AK0011-Kernel-Domain-Model.md` | Task owns TaskExecutionDescriptor, not callable/function |
| 8 | AK0011 lifecycle terminology aligned with KernelObjectState | `AK0011-Kernel-Domain-Model.md` | Removed "kInitialized", "kReady", "kRunning", "kFailed/kDestroyed" |
| 9 | AK0016 TaskExecutionDescriptor section added | `AK0016-Task-Specification.md` | New Chapter 4.3 documenting execution intent descriptor |
| 10 | AK0016 public API table updated | `AK0016-Task-Specification.md` | Removed mutation APIs, added GetExecutionDescriptor() |
| 11 | AK0016 dependency flow corrected | `AK0016-Task-Specification.md` | WorkflowGraph is authoritative; TaskDependency is read-only metadata |
| 12 | AK0016 engineering decisions updated | `AK0016-Task-Specification.md` | Added immutability and Workflow-authority decisions |

### 9.2 Final Architecture State

| Concept | Authority |
|---------|-----------|
| Task identity | TaskID (via TypedKernelObject) - immutable |
| Task lifecycle | KernelObjectState - unified across all Kernel Objects |
| Task execution intent | TaskExecutionDescriptor - immutable after construction |
| Dependency topology | WorkflowGraph - owned by Workflow, single source of truth |
| Task dependency metadata | TaskDependency - read-only, synchronized by Workflow |
| Execution resolution | Future Runtime (AK0030+) - resolves capability to mechanism |
| Task construction | Workflow::AddTask(const TaskExecutionDescriptor&) (primary), TaskBuilder (optional helper) |

### 9.3 Intentionally Unchanged

The following design decisions were validated and intentionally left unchanged:

| Component | Status | Rationale |
|-----------|--------|-----------|
| `state.hpp` | Unchanged | KernelObjectState enums remain as-is |
| `workflow_graph.hpp` | Unchanged | Graph topology unchanged; remains authoritative |
| `graph_algorithms.hpp` | Unchanged | Algorithm interfaces preserved |
| `session.hpp` | Unchanged | Session ownership model unaffected |
| `kernel_handle.hpp` | Unchanged | Reserved for future use |
| AK0012 Foundation | Unchanged | TypedKernelObject, KernelMetadata, ObserverRegistry unchanged |
| AK0013 Topology | Unchanged | WorkflowGraph design preserved |
| AK0014 Session | Unchanged | Session specification unchanged |
| AK0015 Workflow | Unchanged | Workflow specification unchanged |

### 9.4 Consistency Statement

After CR-001A-R1, the Core Domain Architecture is internally consistent:

- **AK0011** defines three Kernel Objects with clear responsibilities. Task describes execution intent.
- **AK0012** provides shared foundation reused by all Kernel Objects.
- **AK0013** defines WorkflowGraph as the authoritative topology.
- **AK0014** defines Session as the ownership root.
- **AK0015** defines Workflow as the container of Tasks and topology.
- **AK0016** defines Task as a structural execution description with immutable execution descriptor and read-only dependency metadata.
- **CR-001A** records all architecture decisions and resolutions.

No contradictions remain across AK0011‚ÄìAK0016 and CR-001A. The architecture is ready for the next phase.


*End of CR-001A ‚Ä?Core Domain Architecture Resolution*
