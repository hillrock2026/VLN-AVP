# AK0022 — Runtime Executor Specification

**Status:** Accepted  
**Version:** Revision 2  
**Layer:** Runtime Layer  
**Depends On:** AK0011, AK0012, AK0013, AK0014, AK0015, AK0016, ADD0001, AK0021, AK0030  

---

## Chapter 1 — Introduction

### 1.1 Purpose

This specification defines the architecture boundary, responsibilities, interfaces, and runtime behavior of the Agent Kernel Executor.

The Executor is the second Runtime component introduced after Core Domain freeze, following the Scheduler (AK0021).

The Executor provides the bridge between Scheduler and Capability Runtime. It transforms scheduling decisions into actual execution by resolving capability requirements and dispatching to the appropriate runtime mechanism.

The Executor does **not** schedule tasks. Scheduling responsibility belongs to the Scheduler (AK0021).

### 1.2 Design Principle

The Executor follows the principle:

> Scheduler decides **WHEN** and **WHAT** can execute. Executor decides **HOW** execution happens.

**Executor owns:**

- Execution request validation
- TaskExecutionDescriptor resolution
- ExecutionContext creation and management
- Execution dispatch
- Completion/failure notification to Scheduler

**Executor does NOT own:**

- Task lifecycle ownership
- Task execution ordering
- Scheduling decisions
- Plugin instantiation or lifetime
- Plugin capability discovery
- WorkflowGraph topology

### 1.3 Relationship to Prior Specifications

```
AK0011 — Core Domain: Task describes intent, not execution
AK0012 — Foundation: TypedKernelObject, KernelObjectState
AK0013 — Topology: WorkflowGraph (Executor does not read it)
AK0014 — Session: unchanged
AK0015 — Workflow: unchanged
AK0016 — Task: TaskExecutionDescriptor (resolved by Executor)
CR-001A — Architecture decisions (preserved)
AK0021 — Scheduler: produces SchedulingDecision (consumed by Executor)
AK0022 — (This spec): Executor as Runtime execution engine
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
Executor (AK0022)
    |
    | ExecutionBinding
    v
Capability Runtime (future AK0030+)
    |
    v
Plugin Runtime (future AK0050+)
```

### 2.2 Executor Boundary

**Executor consumes (read-only):**

| Source | Data | Usage |
|--------|------|-------|
| Scheduler | SchedulingDecision (TaskID, WorkflowID) | Which task to execute |
| Task (via lookup) | TaskExecutionDescriptor | What capability is required |
| Task (via lookup) | TaskContract | Input/output contract |
| Task (via lookup) | KernelObjectState | Task eligibility |

**Executor produces (runtime-only):**

| Output | Type | Consumer |
|--------|------|----------|
| ExecutionRequest | Runtime value object | Internal dispatch |
| ExecutionResult | Runtime value object | Scheduler notification |
| ExecutionContext | Runtime value object | Execution lifetime scope |

**Executor uses (abstract boundary):**

| Abstraction | Purpose |
|-------------|---------|
| CapabilityResolver | Resolves TaskExecutionDescriptor to ExecutionBinding |
| ExecutionBinding | Represents resolved capability ready for dispatch |

**Executor does NOT modify Core Domain ownership.**

---

## Chapter 3 — Executor Responsibilities

### 3.1 Primary Responsibilities

The Executor SHALL:

1. Receive SchedulingDecision from the Scheduler containing TaskID and WorkflowID (Revision 2: SchedulingDecision contains no descriptor).

2. Look up Task via Workflow::FindTask(), obtain descriptor via Task::GetExecutionDescriptor(). Validate execution preconditions: Task exists, Task is in kReady state, descriptor is well-formed.

3. Resolve the Task-owned descriptor into an ExecutionBinding through CapabilityResolver.

4. Create ExecutionContext scoped to a single execution.

5. Dispatch the resolved ExecutionBinding with the ExecutionContext.

6. Receive execution completion or failure.

7. Notify the Scheduler via NotifyCompleted() or NotifyFailed().

### 3.2 Execution Flow

### 3.2 Execution Flow

```
Scheduler
    |
    | SchedulingDecision (TaskID, WorkflowID)
    v
Executor::Submit()
    |
    |-- Phase 1: Precondition Validation
    |   |-- Task exists in Workflow's TaskRegistry
    |   |-- Task state == kReady
    |   |-- TaskExecutionDescriptor is populated
    |   |-- IsResolvable(descriptor) via CapabilityResolver
    |
    |-- Phase 2: Capability Resolution
    |   |-- CapabilityResolver::Resolve(descriptor)
    |   |-- Returns ExecutionBinding or error
    |
    |-- Phase 3: Execution Context Creation
    |   |-- ExecutionID generated
    |   |-- ExecutionContext populated
    |   |-- Cancellation token initialized
    |
    |-- Phase 4: Execution Dispatch
    |   |-- ExecutionBinding::Execute(context)
    |   |-- Execution is asynchronous
    |
    v
Execution (Capability Runtime / Plugin Runtime)
    |
    |-- OnCompletion
    |   |-- ExecutionResult{status: kCompleted}
    |   |-- Scheduler::NotifyCompleted(taskID)
    |
    |-- OnFailure
    |   |-- ExecutionResult{status: kFailed, reason}
    |   |-- Scheduler::NotifyFailed(taskID)
```



```
Scheduler
    |
    | SchedulingDecision (TaskID, WorkflowID)
    v
Executor::Submit()
    |
    | 1. Validate preconditions
    | 2. Resolve descriptor -> ExecutionBinding
    | 3. Create ExecutionContext
    | 4. Dispatch
    v
Execution (Capability / Plugin Runtime)
    |
    v
Executor::OnCompletion / OnFailure
    |
    | 5. Create ExecutionResult
    | 6. Notify Scheduler
    v
Scheduler::NotifyCompleted / NotifyFailed
```

### 3.3 Explicit Non-Responsibilities

| Forbidden | Reason | Owner |
|-----------|--------|-------|
| Choose runnable tasks | Scheduler decides execution order | Scheduler |
| Inspect Workflow topology | Executor does not read WorkflowGraph | Scheduler |
| Modify WorkflowGraph | Core Domain topology ownership | Workflow |
| Own Session | Core Domain ownership | Session |
| Own Workflow | Core Domain ownership | Session |
| Own Task | Core Domain ownership | Workflow |
| Create Plugins | Plugin lifecycle is external | Plugin Runtime |
| Schedule execution order | Scheduler decides ordering | Scheduler |
| Store result inside Task | ExecutionResult is Runtime-only | Executor |
| Replace TaskExecutionDescriptor | Task structural contract | Task |

---

## Chapter 4 — Executor Data Model

### 4.1 ExecutionRequest

ExecutionRequest is a Runtime value object that packages everything needed for a single execution.

```
struct ExecutionRequest {
    TaskID taskID;
    WorkflowID workflowID;
    TaskExecutionDescriptor descriptor;
    ExecutionContext context;
};
```

The ExecutionRequest SHALL NOT contain Task*, Workflow*, Session*, Plugin*, or Executor*.

### 4.2 ExecutionContext

ExecutionContext is a Runtime-only value object scoped to a single execution.

```
struct ExecutionContext {
    ExecutionID executionID;
    WorkflowID workflowID;
    TaskID taskID;
    // CancellationToken cancellationToken;
    // std::chrono::milliseconds timeout;
};
```

The ExecutionContext SHALL NOT be stored inside Task.

### 4.3 ExecutionResult

ExecutionResult is a Runtime-only value object representing the outcome of a single execution.

```
struct ExecutionResult {
    TaskID taskID;
    ExecutionStatus status;
    std::string failureReason;
};
```

The ExecutionResult SHALL NOT be stored inside Task.

### 4.4 ExecutionStatus

```
enum class ExecutionStatus : std::uint8_t {
    kCompleted,
    kFailed,
    kCancelled,
    kTimedOut,
    kUnresolvable
};
```

### 4.5 ExecutionBinding

ExecutionBinding is an abstract handle produced by the CapabilityResolver. It represents a resolved capability ready for execution. The Executor depends only on this abstract concept.

---

## Chapter 5 — Execution Preconditions

### 5.1 Precondition Checks

Before dispatching, the Executor SHALL verify:

| Check | Description | Failure Action |
|-------|-------------|----------------|
| Task exists | TaskID resolves to a valid Task | kUnresolvable |
| Task is kReady | Task state allows execution | kFailed |
| Descriptor present | TaskExecutionDescriptor is populated | kUnresolvable |
| Capability resolvable | CapabilityResolver can produce a binding | kUnresolvable |

### 5.2 Task State During Execution

While a Task is being executed, the Task's KernelObjectState MAY be set to kRunning by the Runtime. Task state transitions belong to the Runtime, not to the Executor alone.

---

## Chapter 6 — Capability Resolution Boundary

### 6.1 Abstract Resolver

The Executor depends on an abstract capability resolver. The resolver is **not** implemented in this specification.

```
// Conceptual abstract interface (future AK0030+)
// class ICapabilityResolver {
//     [[nodiscard]] virtual std::optional<ExecutionBinding> Resolve(
//         const TaskExecutionDescriptor& descriptor) = 0;
// };
```

### 6.2 Resolution Contract

| Input | Output |
|-------|--------|
| descriptor with capability "llm.chat" | ExecutionBinding wrapping an LLM plugin |
| descriptor with capability "code.execute" | ExecutionBinding wrapping a sandbox executor |
| descriptor with capability "http.request" | ExecutionBinding wrapping an HTTP client |

### 6.3 Executor Knows Nothing About

How plugins are loaded, how tools are instantiated, how model instances are managed, or how capability names are registered. These belong to future specifications (AK0030+, AK0050+).

---

## Chapter 7 — Executor Lifecycle

### 7.1 Executor Lifecycle

The Executor lifecycle is independent from KernelObject lifecycle. The Executor is Runtime infrastructure, not a Kernel Object.

```
Created -> Initialized -> Running -> Stopped
```

The Executor lifecycle does **not** introduce new KernelObjectState values.

### 7.2 Task Execution Lifecycle

During a single task execution, the Executor manages:

```
Received -> Validated -> Resolved -> Dispatched -> Completed/Failed
```

This is a per-execution state machine, not a Kernel Object lifecycle.

---

## Chapter 8 — Executor API Contract

### 8.1 IExecutor Interface

```
class IExecutor {
public:
    virtual ~IExecutor() noexcept = default;

    virtual void Submit(SchedulingDecision decision) = 0;
    virtual void Cancel(TaskID task) = 0;
    virtual void Configure(ExecutorConfiguration config) = 0;
    virtual void Initialize() = 0;
    virtual void Shutdown() = 0;
};
```

### 8.2 API Constraints

The Executor API MUST use IDs and Runtime value objects, avoid ownership transfer, and avoid raw Core Domain pointers.

The Executor API MUST NOT expose scheduling methods, Plugin APIs, capability discovery methods, or return Core Domain object pointers.

---

## Chapter 9 — Scheduler-Executor Boundary

### 9.1 Responsibility Separation

| Component | Responsibility |
|-----------|----------------|
| Scheduler | Decides WHEN a task should execute and WHICH task is next |
| Executor | Decides HOW a task executes and dispatches to the capability runtime |

### 9.2 Interaction Contract

```
Scheduler                        Executor
    |                                |
    |--- SchedulingDecision --------->|
    |    (TaskID, WorkflowID)        |
    |                                |
    |                                |--- Validate preconditions
    |                                |--- Resolve capability
    |                                |--- Create ExecutionContext
    |                                |--- Dispatch execution
    |                                |
    |<-- ExecutionResult ------------|
    |    (via NotifyCompleted/       |
    |     NotifyFailed)              |
```

### 9.3 Violation Rules

Neither component may assume the other's responsibility:

**Scheduler MUST NOT:**
- Execute tasks directly
- Create ExecutionContext
- Resolve TaskExecutionDescriptor
- Manage execution lifetime

**Executor MUST NOT:**
- Schedule tasks or determine execution order
- Inspect WorkflowGraph
- Modify scheduling state (ReadyQueue, RunningSet)
- Make scheduling policy decisions

### 9.4 Data Flow Constraints

| Data | Producer | Consumer | Allowed Format |
|------|----------|----------|----------------|
| SchedulingDecision | Scheduler | Executor | Value object (TaskID, WorkflowID, status) |
| ExecutionRequest | Executor | Internal dispatch | Value object (IDs, descriptor, context) |
| ExecutionResult | Executor | Scheduler | Value object (TaskID, status, reason) |
| ExecutionContext | Executor | ExecutionBinding | Runtime-only, not persisted |


### 9.1 Responsibility Separation

| Component | Responsibility |
|-----------|----------------|
| Scheduler | Decides WHEN and WHICH task should execute |
| Executor | Decides HOW a task executes and dispatches |

### 9.2 Interaction Contract

```
Scheduler                      Executor
    |                              |
    |--- SchedulingDecision ------->|
    |                              |--- Validate
    |                              |--- Resolve
    |                              |--- Dispatch
    |<-- ExecutionResult ----------|
```

### 9.3 Violation Rules

- Scheduler MUST NOT execute tasks
- Executor MUST NOT schedule tasks
- Scheduler MUST NOT create ExecutionContext
- Executor MUST NOT inspect WorkflowGraph
- Scheduler MUST NOT resolve capabilities
- Executor MUST NOT modify scheduling state

---

## Chapter 10 — Plugin Boundary

### 10.1 Responsibility Separation

```
Executor                     Plugin Runtime (future)
    |                             |
    |--- ExecutionBinding ------->|
    |    (resolved capability)    |
    |                             |--- Instantiate plugin
    |                             |--- Invoke capability
    |                             |--- Return result
    |<-- ExecutionResult ---------|
```

### 10.2 Executor Non-Responsibilities

| Forbidden | Reason |
|-----------|--------|
| Instantiate plugins | Plugin Runtime manages lifecycle |
| Load plugins | Plugin discovery belongs to Plugin Runtime |
| Discover plugins | Capability registration belongs to Plugin Runtime |
| Manage plugin lifetime | Plugin Runtime manages lifecycle |
| Own plugin instances | Plugin instances managed by Plugin Runtime |

### 10.3 Plugin Contract

The Executor expects the Plugin Runtime to expose:

- A registration mechanism for capability names
- A resolution mechanism from capability name to execution handler
- A lifecycle management interface for plugin instances

None of these are defined or implemented in AK0022. They are reserved for AK0050+.


### 10.1 Responsibility Separation

Executor dispatches via ExecutionBinding. Plugin Runtime performs capability implementation.

The Executor SHALL NOT instantiate, load, discover, or manage plugin lifetime. Those belong to future Plugin Runtime specification.

---

## Chapter 11 — Error Model

### 11.1 Executor Errors

| Error | Description | Status |
|-------|-------------|--------|
| DescriptorNotResolvable | Capability name could not be resolved | kUnresolvable |
| ExecutionTimedOut | Execution exceeded timeout | kTimedOut |
| ExecutionCancelled | Cancelled by request | kCancelled |
| CapabilityUnavailable | Capability temporarily unavailable | kFailed |
| ExecutionFailed | Execution completed with error | kFailed |
| InvalidTaskState | Task not in kReady | kFailed |

### 11.2 Error Ownership

Executor reports errors via ExecutionResult. It does NOT create Task-level error objects, store errors in Task, or implement retry logic.

---

## Chapter 12 — Future Extension Points

The following extension points are explicitly reserved. None are implemented in this specification.

| Extension | Description | Future Specification |
|-----------|-------------|---------------------|
| Distributed execution | Remote worker dispatch | AK00XX |
| Remote worker | Executor delegates execution to remote runtime | AK00XX |
| Persistence | Execution state checkpointing and recovery | AK0060 |
| Tracing | Distributed tracing context propagation | AK00XX |
| Metrics | Execution metrics collection (duration, count, errors) | AK00XX |
| Retry | Automatic retry on transient execution failures | AK00XX |
| Circuit breaker | Protection against repeated capability failures | AK00XX |
| Resource management | CPU, memory, GPU allocation for execution | AK00XX |
| Execution pooling | Pooled execution contexts for performance | AK00XX |
| Preemptive scheduling | Support for executor-level preemption hints | AK00XX |

None of these extensions affect the Core Domain. They extend only the Runtime layer.


| Extension | Specification |
|-----------|--------------|
| Distributed execution | AK00XX |
| Remote worker | AK00XX |
| Persistence | AK0060 |
| Tracing | AK00XX |
| Metrics | AK00XX |
| Retry | AK00XX |
| Circuit breaker | AK00XX |
| Resource management | AK00XX |

---

## Chapter 13 — Engineering Decisions

### Decision 1: Executor Never Schedules

Executor has no scheduling responsibilities. It receives SchedulingDecision and acts on it.

**Reason:** Strict separation of concerns. Scheduler answers "when/which", Executor answers "how".

### Decision 2: Executor Owns ExecutionContext

ExecutionContext is created and owned by the Executor for the duration of a single execution.

**Reason:** Runtime-only data must not leak into Core Domain. Task remains serializable.

### Decision 3: ExecutionResult Belongs to Runtime

ExecutionResult is a Runtime value object. It is not stored inside Task.

**Reason:** Core Domain freeze mandates Task does not own execution results.

### Decision 4: Capability Resolution is Abstract

Executor depends on an abstract CapabilityResolver interface.

**Reason:** Capability resolution belongs to the Capability Runtime (future AK0030+).

### Decision 5: Plugin Lifetime is External

Executor does not instantiate, load, discover, or manage plugin lifetime.

**Reason:** Plugin lifecycle belongs to the Plugin Runtime (future AK0050+).

### Decision 6: Task Remains Immutable During Execution

Executor reads Task data but does not modify it.

**Reason:** Task is a structural description. Runtime state management belongs to a higher-level Runtime orchestrator.

### Decision 7: Executor Communicates Only Through Runtime Value Objects

All inputs and outputs are Runtime value objects. No Core Domain pointers cross the Executor boundary.

**Reason:** Prevents lifetime coupling. Enables future distributed execution.

---

## Chapter 14 — Conformance Criteria

An implementation conforms to AK0022 if:

### Architecture
- Executor exists only in Runtime layer
- Core Domain (AK0011-AK0016) unchanged
- AK0021 (Scheduler) unchanged
- No new KernelObjectState values

### Ownership
- Executor does not own Session, Workflow, or Task
- Executor does not own Plugin instances
- Executor uses IDs and Runtime value objects, not Core Domain pointers

### Task Invariance
- Task remains structural description
- TaskExecutionDescriptor remains WHAT-only
- Task does not gain Execute(), Run(), or Dispatch()
- Task does not store ExecutionResult or ExecutionContext

### Boundary
- Scheduler remains execution-order authority
- WorkflowGraph remains topology authority
- Capability resolution is abstract
- Plugin lifecycle is external

### Runtime Objects
- ExecutionContext is Runtime-only
- ExecutionResult is Runtime-only
- ExecutionRequest contains IDs only

---

## Chapter 15 — Final Architecture Statement

AK0022 introduces the second Runtime behavior component.

The Executor provides execution dispatch while preserving the Core Domain boundary and the Scheduler-Executor separation:

```
Core Domain -> Scheduler -> Executor -> Capability Runtime -> Plugin Runtime
```

The Executor is a **runtime execution engine**, not a scheduler, not a plugin container, and not an owner of Core Domain objects.
