# AVP-1 Core Foundation — Architecture Summary

**Date:** 2026-07-09  
**Specification:** AK0011-Kernel-Domain-Model.md  
**Interface Skeletons:** 6 headers in `include/agent_kernel/`

---

## 1. Architecture Decisions

### Decision 1: Three Kernel Objects Only

Session, Workflow, and Task are the initial Kernel Objects. Memory, Context, Scheduler, Executor, EventBus, and Plugin are deliberately deferred.

**Rationale:** Validating the core ownership hierarchy (Session owns Workflow owns Task) before adding cross-cutting concerns avoids architectural coupling. Memory and Context will be injected as services, not additional composition layers.

### Decision 2: Typed IDs (Not Typedefs)

SessionID, WorkflowID, and TaskID are distinct types inheriting from KernelObjectID, not typedefs.

**Rationale:** Prevents accidental cross-type assignment. A function expecting `WorkflowID` cannot accept a `TaskID` at compile time. The cost is minimal (empty base optimization applies).

### Decision 3: Composition via unique_ptr

All parent-child relationships use `std::unique_ptr<T>` stored in `OwningCollection<T>` (alias for `vector<unique_ptr<T>>`).

**Rationale:** Explicit ownership, no garbage collection, deterministic destruction. The `OwningCollection` alias documents intent at the type level.

### Decision 4: Observer Pattern for Cross-Object Communication

Objects communicate through dedicated observer interfaces (ISessionObserver, IWorkflowObserver, ITaskObserver), not through direct member access.

**Rationale:** Decouples Kernel Objects from each other and from external consumers (plugins, monitoring, EventBus). A plugin simply implements an observer interface.

### Decision 5: Single Unified State Machine

All Kernel Objects share `KernelObjectState` and the same transition rules.

**Rationale:** Simplifies the Scheduler and Executor (they only need to understand one state model). Ensures consistent lifecycle semantics across all objects.

### Decision 6: Session as Top-Level Object

Session is the root of the ownership tree. Kernel Runtime creates Sessions. Sessions own Workflows. Workflows own Tasks.

**Rationale:** Session provides the natural isolation boundary (one Session cannot affect another). Resource cleanup is deterministic — destroying a Session destroys all its children.

---

## 2. Trade-offs

| Trade-off | Choice | Cost |
|-----------|--------|------|
| **Typed IDs vs. single ID type** | Typed IDs (SessionID, WorkflowID, TaskID) | More types to maintain. Callers must convert explicitly when storing in heterogeneous collections. |
| **Composition vs. shared ownership** | Strict unique_ptr composition | Cannot share Kernel Objects across Sessions. If sharing is needed later, an explicit `Clone()` or `Detach()` protocol must be designed. |
| **Unified state vs. per-object states** | Single KernelObjectState | Some states may not apply to all objects (e.g., Task does not have Suspended in the initial model). Future revisions may add per-object state masks. |
| **Observer pattern vs. direct callbacks** | Observer interfaces | More boilerplate. Each observer interface requires registration/deregistration. Benefits for plugin systems justify the cost. |
| **Deferred Scheduler/Executor** | Session and Workflow do not execute | Cannot run anything until AK0030+. This is intentional — AVP-1 validates the domain model, not execution. |

---

## 3. Future Extension Points

| Extension Point | Current Design | How to Extend |
|----------------|---------------|---------------|
| Memory integration | Not present | Add `SetMemory()` / `GetMemory()` to Session. Inject Memory into Workflow/Task via constructor or setter. |
| Context integration | Not present | Add `ContextID` to Task. Session creates root Context; Workflow creates scoped contexts. |
| Scheduler | Not present | Session exposes a `Submit(Workflow&)` method that accepts an `IScheduler&`. Workflow submits individual Tasks. |
| Executor | Not present | Executor receives a Task reference and calls its execution callback. Scheduler dispatches to Executor. |
| EventBus | Not present | Bridge observer interfaces to EventBus topics. Observers publish events; subscribers receive them. |
| Plugin System | Not present | Plugins implement observer interfaces (ISessionObserver, etc.) and attach to Kernel Objects. |
| Distributed execution | KernelObjectID supports UUID extension | Replace uint64_t with a UUID-based ID. Add location/partition field to KernelObjectID. |
| Async/concurrent execution | All interfaces support it | Observer callbacks are natural async boundaries. Add `std::future<Result>` return types to execution methods. |
| Persistence | Not present | Add `Serialize()` / `Deserialize()` methods to each Kernel Object. KernelObjectID provides the stable key. |

---

## 4. Known Limitations

| Limitation | Impact | Resolution |
|------------|--------|------------|
| No input/output data model | Task cannot receive or produce data | Deferred to AK0020+ when Memory and Context are specified |
| No execution callback | Task has no callable to execute | Deferred to AK0030+ when Executor is specified |
| No error propagation beyond observers | Errors are observed but not propagated to parent objects automatically | Deferred to AK0020+ when the error handling model is refined |
| No graph validation algorithm | Workflow::Validate() declared but not implemented | Deferred to implementation phase (AVP-1 code generation) |
| No serialization | Cannot persist or transmit Kernel Objects | Deferred to AK0060+ (Kernel Runtime) |
| No thread safety annotations | Interfaces do not specify thread safety | Deferred to implementation phase (per-object analysis) |

---

## 5. Interface Skeleton Inventory

| File | Lines | Declares |
|------|-------|----------|
| `object_id.hpp` | ~70 | KernelObjectID, SessionID, WorkflowID, TaskID, std::hash specializations |
| `state.hpp` | ~55 | KernelObjectState enum, transition utilities |
| `relationship.hpp` | ~45 | ExclusiveOwnership, ObservedReference, SharedObservation, DependencyDescriptor, OwningCollection |
| `session.hpp` | ~70 | Session class, ISessionObserver interface |
| `workflow.hpp` | ~75 | Workflow class, IWorkflowObserver interface |
| `task.hpp` | ~65 | Task class, ITaskObserver interface |

---

## 6. Verification Against Acceptance Criteria

| Criterion | Status |
|-----------|--------|
| Session owns Workflow | ✅ Composition via OwningCollection<Workflow> |
| Workflow owns Task | ✅ Composition via OwningCollection<Task> |
| Ownership is explicit | ✅ unique_ptr + OwnershipTag types |
| Identity is unified | ✅ KernelObjectID base + typed derived IDs |
| Lifecycle is unified | ✅ Single KernelObjectState for all objects |
| Future Memory integration | ✅ Session reserved SetMemory/GetMemory |
| Future Context integration | ✅ Workflow/Task reserved context |
| Scheduler dependency planned | ✅ Session::Start() delegates to future IScheduler |
| Executor dependency planned | ✅ Task::Execute() reserved |
| Plugin extension possible | ✅ Observer interfaces are natural plugin hooks |
| No runtime implementation | ✅ No .cpp files, no inline code, no algorithms |
