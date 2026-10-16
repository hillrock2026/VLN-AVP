# AK0021 — Runtime Scheduler Specification

**Status:** Accepted  
**Version:** Revision 2  
**Layer:** Runtime Layer  
**Depends On:** AK0011, AK0012, AK0013, AK0014, AK0015, AK0016, ADD0001, AK0030  

---

## Chapter 1 — Introduction

### 1.1 Purpose

This specification defines the architecture boundary, responsibilities, interfaces, and runtime behavior of the Agent Kernel Scheduler.

The Scheduler is the first Runtime component introduced after Core Domain freeze.

The Scheduler provides the bridge between:

```
Core Domain
    |
    v
Runtime Scheduling
```

It transforms static workflow topology into ordered execution decisions.

The Scheduler does **not** execute tasks. Execution responsibility belongs to future Runtime Executor components (AK0022+).

### 1.2 Design Principle

The Scheduler follows the principle:

> Scheduler decides **WHEN** and **WHAT** can execute. Executor decides **HOW** execution happens.

**Scheduler owns:**

- Readiness evaluation
- Dependency satisfaction checking
- Runnable task selection
- Scheduling policy
- Execution ordering decisions

**Scheduler does NOT own:**

- Task lifecycle ownership
- Task execution logic
- Plugin invocation
- Runtime resources
- Execution results

### 1.3 Relationship to Prior Specifications

```
AK0011 ─── Core Domain: Session owns Workflow owns Task
AK0012 ─── Foundation: TypedKernelObject, KernelObjectState
AK0013 ─── Topology: WorkflowGraph (read by Scheduler)
AK0014 ─── Session: unchanged
AK0015 ─── Workflow: provides Task access
AK0016 ─── Task: structural description (read by Scheduler)
CR-001A ── Architecture decisions (preserved)
AK0021 ─── (This spec): Scheduler as Runtime decision engine
```

---

## Chapter 2 — Architectural Position

### 2.1 Runtime Architecture

```
                Core Domain
====================================

Session
   |
Workflow
   |
Task
   |
WorkflowGraph


                Runtime Layer
====================================

Scheduler (AK0021)

        |
        | SchedulingDecision
        v

Executor (AK0022+)

        |
        | Execution
        v

Plugin / Capability Runtime
```

### 2.2 Scheduler Boundary

**Scheduler consumes (read-only):**

| Core Domain Object | Usage |
|--------------------|-------|
| `Workflow` | Scope for scheduling |
| `WorkflowGraph` | Topology authority for dependency evaluation |
| `Task` | Task identity, state, contract, execution descriptor |
| `TaskContract` | Owned by Task; input/output contract metadata |
| `TaskExecutionDescriptor` | Owned by Task; not consumed by Scheduler (see AK0016 Rev 2) |
| `KernelObjectState` | Task lifecycle state for eligibility |

**Scheduler produces (runtime-only):**

| Decision Type | Description |
|---------------|-------------|
| `SchedulingDecision` | Which Task to execute next |
| `RunnableTaskSet` | Set of currently eligible Tasks |
| `ExecutionOrder` | Determined ordering for a Workflow |

**Scheduler does NOT modify Core Domain ownership.**

---

## Chapter 3 — Scheduler Responsibilities

### 3.1 Primary Responsibilities

The Scheduler SHALL:

#### 1. Discover Runnable Tasks

Given a Workflow:

```
WorkflowGraph
       |
       v
Dependency Analysis
       |
       v
Runnable Tasks
```

The Scheduler evaluates:

- **Dependencies satisfied**: All upstream Tasks completed successfully
- **Task state eligible**: Task is in `kReady` state
- **Scheduling policy allows**: Policy-specific constraints satisfied

#### 2. Maintain Scheduling State

The Scheduler maintains runtime-only scheduling state:

| State | Type | Purpose |
|-------|------|---------|
| Ready Queue | Ordered collection of runnable `SchedulingItem` instances | Tasks ready for execution, ordered by policy |
| Running Set | Set of `TaskID` currently dispatched | Tasks currently executing |
| Completed Tracking | Set of `TaskID` completed successfully | Dependency satisfaction tracking |
| Failed Tracking | Set of `TaskID` that failed | Error propagation and workflow handling |

These states belong to the Runtime layer. They are NOT stored inside Core Domain objects.

#### 3. Apply Scheduling Policy

The Scheduler determines execution order using a replaceable policy:

| Policy | Behavior |
|--------|----------|
| FIFO | Simple queue order |
| Priority-based | Uses Task priority metadata |
| Deadline-based | Uses execution deadline metadata |
| Resource-aware | Considers capability/resource availability |

Scheduling policy is a replaceable component (see Chapter 9).

### 3.2 Explicit Non-Responsibilities

| Forbidden | Reason |
|-----------|--------|
| Execute Task | Executor responsibility (AK0022+) |
| Store Task ownership | Workflow owns Task (AK0011) |
| Modify WorkflowGraph directly | Core Domain topology ownership (AK0013) |
| Create Plugin instances | Plugin Runtime responsibility |
| Produce execution result | Executor responsibility |
| Replace TaskExecutionDescriptor | Task structural contract (AK0016, CR-001A) |
| Introduce new KernelObjectState | Core Domain freeze (Decision 4) |

---

## Chapter 4 — Scheduler Data Model

### 4.1 Scheduler Runtime State

```cpp
class SchedulerState {
    ReadyQueue readyQueue;
    RunningTasks running;
    CompletedTasks completed;
    FailedTasks failed;
};
```

This state exists only during Runtime execution. It is not persisted in Core Domain objects.

### 4.2 SchedulingItem

The Scheduler operates on lightweight scheduling items:

```cpp
struct SchedulingItem {
    TaskID taskID;
    WorkflowID workflowID;
    int priority;
    Timestamp enqueueTime;
};
```

The Scheduler stores references **by ID only**. The Scheduler does **not** own Task objects. The Scheduler does **not** own or carry TaskExecutionDescriptor. Descriptor resolution occurs downstream in the Executor via Task::GetExecutionDescriptor().

### 4.3 SchedulingDecision

```cpp
struct SchedulingDecision {
    std::optional<TaskID> nextTask;    // Empty if no runnable task
    WorkflowID workflowID;
    SchedulingStatus status;
};
```

### 4.4 SchedulingStatus

```cpp
enum class SchedulingStatus : std::uint8_t {
    kTaskReady,          // A runnable task was selected
    kWorkflowCompleted,  // All tasks in workflow completed
    kWorkflowFailed,     // A task failed, workflow cannot proceed
    kIdle,               // No runnable tasks at this time
    kWaiting             // Waiting for external dependencies
};
```

---

## Chapter 5 — Runnable Task Definition

### 5.1 Runnable Criteria

A Task is **runnable** when ALL of the following are true:

```
Task State == kReady
```
AND:
```
All required dependencies completed
```
AND:
```
Scheduling policy allows execution
```

### 5.2 Dependency Evaluation

The Scheduler reads **WorkflowGraph** as the **only** topology authority.

Dependency evaluation flow:

```
WorkflowGraph
      |
      v
GetPredecessors(taskId)
      |
      v
For each predecessor:
  Is predecessor in CompletedTracking?
      |
      v
ALL completed → Task is dependency-satisfied
ANY failed    → Task is blocked
```

The Scheduler MUST NOT use `TaskDependency` as topology authority. `TaskDependency` remains descriptive metadata (per CR-001A).

---

## Chapter 6 — Scheduler Lifecycle

### 6.1 Scheduler Lifecycle

The Scheduler lifecycle is independent from KernelObject lifecycle. The Scheduler is Runtime infrastructure, not a Kernel Object.

```
Created
   |
Initialized
   |
Running
   |
Stopped
```

The Scheduler lifecycle does **not** introduce new KernelObjectState values. These are Scheduler-internal operational states, not architecture-level lifecycle states.

### 6.2 Workflow Scheduling Lifecycle

When a Workflow is attached to the Scheduler:

```
Workflow
   |
   v
Scheduler::Attach(workflowID)
   |
   v
Analyze WorkflowGraph
   |
   v
Identify root nodes (no dependencies)
   |
   v
Enqueue root nodes as initial ReadyQueue
   |
   v
For each scheduling cycle:
   |
   v
Scheduler::Next() → SchedulingDecision
   |
   v
On completion notification:
   Scheduler::NotifyCompleted(taskID)
       |
       v
   Mark task completed
   Evaluate downstream tasks
   Enqueue newly runnable tasks
   |
   v
On failure notification:
   Scheduler::NotifyFailed(taskID)
       |
       v
   Mark workflow as failed (depending on policy)
```

---

## Chapter 7 — Scheduler API Contract

### 7.1 IScheduler Interface

```cpp
class IScheduler {
public:
    virtual ~IScheduler() noexcept = default;

    // Attach a workflow to the scheduler.
    // The scheduler analyzes the WorkflowGraph and prepares
    // initial scheduling state.
    virtual void Attach(WorkflowID workflow) = 0;

    // Detach a workflow. Releases scheduler-internal state.
    virtual void Detach(WorkflowID workflow) = 0;

    // Return the next task to execute, or empty if none available.
    // This is the primary scheduling decision method.
    [[nodiscard]] virtual SchedulingDecision Next() = 0;

    // Notify the scheduler that a task completed successfully.
    virtual void NotifyCompleted(TaskID task) = 0;

    // Notify the scheduler that a task failed.
    virtual void NotifyFailed(TaskID task) = 0;
};
```

### 7.2 API Constraints

**The Scheduler API MUST:**

- Use IDs (`TaskID`, `WorkflowID`) exclusively
- Avoid ownership transfer of Core Domain objects
- Avoid raw `Task*` or `Task&` parameters

**The Scheduler API MUST NOT:**

- Expose `Execute()`, `Run()`, or `Dispatch()` — those belong to Executor
- Expose Plugin APIs
- Expose Runtime resource management APIs

---

## Chapter 8 — Scheduler and Executor Boundary

### 8.1 Interaction Model

```
Scheduler               Executor
    |                       |
    |--- SchedulingDecision |
    |   (TaskID,            |
    |    WorkflowID,        |
    |    SchedulingStatus)  |
    |                       |
    |                       |--- executes task
    |                       |
    |<-- ExecutionResult ---|
    |   (Completed / Failed)|
    |                       |
```

**Scheduler sends to Executor:**

- `TaskID` — which task to execute
- `WorkflowID` — owning workflow for Task lookup
- `SchedulingStatus` — workflow scheduling state

**Executor obtains from Task ownership (Revision 2):**

- `TaskExecutionDescriptor` — via Task::GetExecutionDescriptor()
- `TaskContract` — via Task::GetContract()

**Executor returns to Scheduler:**

- `Completed(TaskID)` — task finished successfully
- `Failed(TaskID)` — task finished with error

### 8.2 Separation Rule

| Component | Question |
|-----------|----------|
| Scheduler | **Which** Task should run next? |
| Executor | **How** does this Task run? |

---

## Chapter 9 — Scheduling Policies

### 9.1 Policy Abstraction

Scheduling policy SHALL be replaceable:

```cpp
class ISchedulingPolicy {
public:
    virtual ~ISchedulingPolicy() noexcept = default;

    [[nodiscard]] virtual std::optional<SchedulingItem> Select(
        const std::vector<SchedulingItem>& runnableTasks) = 0;
};
```

### 9.2 Initial Policies

**FIFO Scheduler:** Simple queue order. Tasks are executed in the order they become runnable.

**Priority Scheduler:** Uses task priority metadata (from `KernelMetadata` or `SchedulingItem`) to order execution. Higher priority tasks execute first.

**Dependency Scheduler:** Uses graph readiness. Tasks with more downstream dependencies execute first (critical path priority).

---

## Chapter 10 — Error Handling

### 10.1 Scheduler Errors

| Error | Description |
|-------|-------------|
| InvalidWorkflow | Attached WorkflowID does not exist |
| MissingDependency | Dependency evaluation failed due to missing graph data |
| NoRunnableTask | All tasks are blocked or completed |
| CircularDependency | Graph validation detected a cycle |

### 10.2 Error Ownership

The Scheduler reports errors via `SchedulingDecision.status` or dedicated failure signals.

The Scheduler does **not** create:
- Task execution results
- Task output data
- Runtime error objects that belong to Executor

---

## Chapter 11 — Persistence and Distribution

Not included in AK0021. Reserved for:

- AK0060 — Persistence
- Distributed Runtime specifications

Scheduler state serialization, checkpointing, and distributed scheduling are future work.

---

## Chapter 12 — Engineering Decisions

### Decision 1: Scheduler Does Not Own Task

**Decision:** The Scheduler stores `TaskID` only, never `Task*` or `unique_ptr<Task>`.

**Reason:** Core Domain ownership remains: Session → Workflow → Task. The Scheduler is a Runtime observer/consumer of Core Domain objects.

### Decision 2: WorkflowGraph is Scheduling Topology Authority

**Decision:** The Scheduler reads `WorkflowGraph` exclusively for dependency topology.

**Reason:** Avoid conflicting views between `TaskDependency` and `WorkflowGraph`. CR-001A already established WorkflowGraph as the sole topology authority.

### Decision 3: Scheduler Does Not Execute

**Decision:** The Scheduler produces decisions. The Executor performs execution.

**Reason:** Maintains clear separation: Decision → Execution. Enables independent evolution of scheduling policies and execution mechanisms.

### Decision 4: Scheduler Runtime State is External

**Decision:** Scheduling state (ReadyQueue, RunningSet, etc.) lives in the Scheduler, not in Core Domain objects.

**Reason:** Core Domain remains serializable, deterministic, and independent from execution environment. Task does not know about scheduling state.

### Decision 5: Scheduler Uses IDs, Not Pointers

**Decision:** All Scheduler API uses typed IDs (`TaskID`, `WorkflowID`).

**Reason:** Avoids lifetime coupling. Allows future distributed scheduling where objects may reside on different nodes.

### Decision 6: No New KernelObjectState Values

**Decision:** The Scheduler uses `KernelObjectState` for Task eligibility evaluation. No new state values are introduced.

**Reason:** Core Domain freeze (Decision 4 in CR-001A) mandates exactly 8 states: kCreated through kDestroyed.

---

## Chapter 13 — Conformance Criteria

An implementation conforms to AK0021 if and only if ALL of the following are true:

### Architecture

- [ ] Scheduler exists only in Runtime layer
- [ ] Core Domain (AK0011–AK0016) remains unchanged
- [ ] No new KernelObjectState values introduced

### Ownership

- [ ] Scheduler does not own Session
- [ ] Scheduler does not own Workflow
- [ ] Scheduler does not own Task
- [ ] Scheduler uses IDs, not raw pointers to Core Domain objects

### Dependency

- [ ] WorkflowGraph is the only topology authority for scheduling
- [ ] Scheduler does not use TaskDependency as topology authority

### Execution

- [ ] Scheduler does not execute Tasks
- [ ] Executor remains responsible for execution
- [ ] Scheduler API does not expose Execute() or Run()

### Lifecycle

- [ ] Scheduler lifecycle is independent from KernelObjectState
- [ ] No new KernelObjectState values introduced

### Extensibility

- [ ] Scheduling policy is replaceable
- [ ] Scheduler supports future priority, distributed, and resource-aware policies

---

## Final Architecture Statement

AK0021 introduces the first Runtime behavior component.

The Scheduler provides execution ordering decisions while preserving the Core Domain boundary:

```
Core Domain
    |
    | describes intent
    v
Scheduler (AK0021)
    |
    | chooses execution order
    v
Executor (AK0022+)
    |
    | performs execution
    v
Capability Runtime
```

The Scheduler is therefore a **runtime decision engine**, not an execution engine.
