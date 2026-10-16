# AK0023 - Capability Resolution Specification
**Canonical Runtime Name:** AK0023 — Runtime CapabilityResolver Specification

**Status:** Accepted
**Version:** Revision 2
**Layer:** Runtime Layer
**Depends On:** AK0011, AK0012, AK0013, AK0014, AK0015, AK0016, ADD0001, AK0021, AK0022, AK0030

---

## Chapter 1 - Introduction

### 1.1 Purpose

This specification defines the architecture boundary, responsibilities, interfaces, and data model of the Agent Kernel Capability Resolver.

Capability Resolution is the third Runtime component introduced after Core Domain freeze, following the Scheduler (AK0021) and Executor (AK0022).

The Capability Resolver answers exactly one question:

> Which Runtime capability should execute this Task?

It does **not** execute anything. Execution belongs to the Executor (AK0022). Scheduling belongs to the Scheduler (AK0021). Plugin loading belongs to future Plugin Runtime.

### 1.2 Design Principle

The Capability Resolver follows the principle:

> Task describes **WHAT** capability is needed. Resolver finds **WHICH** capability satisfies it. Executor performs **HOW** execution happens.

**Resolver owns:**
- TaskExecutionDescriptor resolution
- Capability matching and validation
- ExecutionBinding creation
- Resolution failure reporting

**Resolver does NOT own:**
- Task execution
- Task scheduling
- Plugin instantiation or lifetime
- Plugin loading or unloading
- Task state or execution results
- Execution context or execution requests

### 1.3 Relationship to Prior Specifications

`
AK0011 - Core Domain: Task describes execution intent
AK0012 - Foundation: TypedKernelObject, KernelObjectState
AK0013 - Topology: WorkflowGraph (Resolver does not read it)
AK0014 - Session: unchanged
AK0015 - Workflow: unchanged
AK0016 - Task: TaskExecutionDescriptor (resolved by Resolver)
CR-001A - Architecture decisions (preserved)
AK0021 - Scheduler: unchanged
AK0022 - Executor: consumes SchedulingDecision; uses Resolver
AK0023 - (This spec): Capability Resolver
`

---

## Chapter 2 - Architectural Position

### 2.1 Runtime Architecture

`
                Core Domain
====================================

Session, Workflow, Task, WorkflowGraph


                Runtime Layer
====================================

Scheduler (AK0021)
    |
    | SchedulingDecision
    v
Executor (AK0022)
    |
    | ExecutionRequest
    v
Capability Resolver (AK0023)
    |
    | ExecutionBinding
    v
(Future) Plugin Runtime
`

### 2.2 Resolver Boundary

The Capability Resolver sits between the Executor and the future Plugin Runtime. It consumes TaskExecutionDescriptor and produces ExecutionBinding.

**Resolver consumes (read-only):**

| Source | Data | Usage |
|--------|------|-------|
| Executor | TaskExecutionDescriptor | Capability name, version constraint, hints |
| Executor | ExecutionRequest (contextual) | Execution metadata for resolution |
| System | Capability registry (abstract) | Known capabilities |

**Resolver produces:**

| Output | Type | Consumer |
|--------|------|----------|
| ExecutionBinding | Runtime value object | Executor |

Resolver does **not** modify Core Domain ownership.

---

## Chapter 3 - Responsibilities

### 3.1 Primary Responsibilities

The Capability Resolver SHALL:

1. Resolve TaskExecutionDescriptor into an executable binding
2. Locate the matching Runtime capability by name
3. Validate capability compatibility (version, parameters)
4. Produce an immutable ExecutionBinding
5. Report resolution failure with diagnostic information

### 3.2 Resolution States

`
Received --> Matching --> Validating --> Bound
                              |
                              v
                          Failed
`

Each resolution is stateless. The Resolver holds no per-Task state across resolutions.

### 3.3 Explicit Non-Responsibilities

| Forbidden | Reason | Owner |
|-----------|--------|-------|
| Execute Task | Executor responsibility | Executor (AK0022) |
| Schedule Task | Scheduler responsibility | Scheduler (AK0021) |
| Own WorkflowGraph | Core Domain ownership | Workflow (AK0013) |
| Own Task | Core Domain ownership | Workflow (AK0015) |
| Own Session | Core Domain ownership | Session (AK0014) |
| Own Plugin lifetime | Plugin Runtime responsibility | Plugin Runtime (future) |
| Load/Unload Plugin | Plugin Runtime responsibility | Plugin Runtime (future) |
| Instantiate Plugin | Plugin Runtime responsibility | Plugin Runtime (future) |
| Cache Task state | Task owns its state | Task (AK0016) |
| Own execution result | Executor responsibility | Executor (AK0022) |
| Store ExecutionBinding in Task | Binding is Runtime-only | Resolver (AK0023) |

---

## Chapter 4 - Runtime Boundary

### 4.1 Ownership Separation

`
Executor owns:     ExecutionContext, ExecutionRequest, ExecutionResult
Capability Resolver owns: ExecutionBinding, CapabilityResolution, CapabilityResolutionStatus
Task owns:         TaskExecutionDescriptor
`

### 4.2 Type Boundaries

| Object | Layer | Owner |
|--------|-------|-------|
| TaskExecutionDescriptor | Core Domain | Task (value type) |
| ExecutionRequest | Runtime | Executor (value type) |
| ExecutionContext | Runtime | Executor (value type) |
| ExecutionBinding | Runtime | Resolver (value type) |
| CapabilityResolution | Runtime | Resolver (value type) |
| Plugin (future) | Runtime | Plugin Runtime |

### 4.3 Rule

Task never owns ExecutionBinding. ExecutionBinding is a Runtime-only value object.

---

## Chapter 5 - Resolution Model

### 5.1 Resolution Input

The Capability Resolver receives a TaskExecutionDescriptor containing:
- Capability name (e.g., llm.chat, code.execute)
- Version constraint (e.g., >=1.0, <2.0)
- Advisory hints (e.g., priority, expected duration)

### 5.2 Resolution Output

The Capability Resolver returns an ExecutionBinding containing:
- Resolved CapabilityIdentifier
- BindingStatus (kReady, kStale, kInvalid)
- Capability version
- Resolution diagnostics

### 5.3 Matching Strategy

The Resolver matches by:
1. Capability name exact match
2. Version constraint satisfaction
3. Capability availability (is the capability currently accessible?)

The matching strategy may be extended by future specifications.

---

## Chapter 6 - ExecutionBinding

ExecutionBinding is a Runtime value object representing a successfully resolved capability ready for execution.

**Properties:**
- Immutable after creation
- Not owned by Task
- Not cached inside Core Domain objects
- Used by Executor to dispatch execution

The concrete execution mechanism behind ExecutionBinding is opaque to the Resolver. The Resolver produces the binding; the Executor and future Plugin Runtime know how to execute it.

**Structure:**
`
struct ExecutionBinding {
    CapabilityIdentifier capabilityID;
    BindingStatus status;
    CapabilityVersion capabilityVersion;
};
`

---

## Chapter 7 - Capability Resolution Flow

### 7.1 Complete Runtime Flow

`
Scheduler
    |
    | SchedulingDecision
    v
Executor
    |
    | 1. Validate preconditions
    | 2. Create ExecutionContext
    | 3. Call Resolver::Resolve(descriptor)
    v
Capability Resolver
    |
    | 1. Extract capability name and version
    | 2. Match against known capabilities
    | 3. Validate version compatibility
    | 4. Check availability
    | 5. Create ExecutionBinding
    |
    v
ExecutionBinding (returned to Executor)
    |
    v
Executor dispatches execution via binding
    |
    v
Scheduler receives ExecutionResult
`

### 7.2 Resolution Steps

Step 1: Receive TaskExecutionDescriptor from Executor
Step 2: Extract capability name and version constraint
Step 3: Match against known capabilities
Step 4: Validate version compatibility
Step 5: Verify capability availability
Step 6: Create CapabilityResolution with status
Step 7: If successful, create ExecutionBinding
Step 8: Return ExecutionBinding to Executor

### 7.3 Post-Resolution

The Executor receives the ExecutionBinding and performs execution. The Resolver has no knowledge of execution outcome.

---

## Chapter 8 - Failure Model

### 8.1 Resolution Failure Categories

| Failure | Description |
|---------|-------------|
| CapabilityNotFound | No capability matches the requested name |
| VersionMismatch | Capability exists but version constraint not satisfied |
| UnsupportedCapability | Capability known but not currently supported |
| ResolverUnavailable | Resolver is not initialized or unavailable |
| BindingCreationFailed | Capability matched but binding could not be created |
| ResolverInternalError | Unexpected Resolver error |

### 8.2 Error Ownership

The Resolver:
- Reports failures via CapabilityResolutionStatus
- Does **not** modify Task state
- Does **not** create Task-level error objects
- Does **not** implement retry logic (belongs to Executor or future Runtime policy)

---

## Chapter 9 - Data Model

### 9.1 CapabilityIdentifier

`
struct CapabilityIdentifier {
    std::string name;       // Canonical capability name
    std::string provider;   // Provider namespace
    uint32_t version;       // Resolved version
};
`

### 9.2 CapabilityVersion

`
struct CapabilityVersion {
    uint32_t major, minor, patch;
};
`

### 9.3 CapabilityResolution

`
struct CapabilityResolution {
    CapabilityIdentifier capabilityID;
    ResolutionStatus status;
    ResolutionDiagnostics diagnostics;
    ExecutionBinding binding;
};
`

### 9.4 ResolutionStatus

`
enum class ResolutionStatus : uint8_t {
    kResolved, kCapabilityNotFound, kVersionMismatch,
    kUnsupported, kResolverUnavailable, kBindingFailed, kInternalError
};
`

### 9.5 BindingStatus

`
enum class BindingStatus : uint8_t { kReady, kStale, kInvalid };
`

### 9.6 ResolutionDiagnostics

`
struct ResolutionDiagnostics {
    string message;
    vector<string> suggestedAlternatives;
};
`

---

## Chapter 10 - Resolver Lifecycle

### 10.1 Resolver Lifecycle

The Resolver lifecycle is independent from KernelObject lifecycle. The Resolver is Runtime infrastructure, not a Kernel Object.

`
Uninitialized -> Initialized -> Running -> Shutdown
`

The Resolver lifecycle does **not** introduce new KernelObjectState values.

### 10.2 Per-Resolution Lifecycle

Each call to Resolve() is stateless and independent:

`
Receive descriptor -> Match -> Validate -> Return binding or failure
`

No per-Task state persists between resolutions.

---

## Chapter 11 - API Contract

### 11.1 ICapabilityResolver Interface

`
class ICapabilityResolver {
public:
    virtual ~ICapabilityResolver() noexcept = default;

    [[nodiscard]] virtual CapabilityResolution Resolve(
        const TaskExecutionDescriptor& descriptor) = 0;

    [[nodiscard]] virtual bool Supports(
        const std::string& capabilityName) const = 0;

    [[nodiscard]] virtual bool Validate(
        const TaskExecutionDescriptor& descriptor) const = 0;

    virtual void Initialize() = 0;
    virtual void Shutdown() = 0;
};
`

### 11.2 API Constraints

**MUST:** Use value types only, avoid Core Domain pointers, be stateless.

**MUST NOT:** Expose LoadPlugin/UnloadPlugin/CreatePlugin/DestroyPlugin, expose Execute() or scheduling methods, accept Task*/Workflow*/Session*, modify Core Domain.

---

## Chapter 12 - Dependency Rules

### 12.1 Allowed Dependencies

| Dependency | Form | Reason |
|------------|------|--------|
| TaskExecutionDescriptor | const reference | Resolution input |
| ExecutionRequest (future) | const reference | Contextual metadata |
| ExecutionContext (future) | const reference | Execution environment info |

### 12.2 Forbidden Dependencies

| Dependency | Reason |
|------------|--------|
| Task* | Lifetime coupling, Core Domain violation |
| Workflow* | Lifetime coupling, Core Domain violation |
| Session* | Lifetime coupling, Core Domain violation |
| WorkflowGraph* | Topology is not a resolution concern |
| Scheduler | Scheduling is separate from resolution |
| Plugin* | Plugin lifetime is external to Resolver |
| Executor* | Executor calls Resolver; reverse not allowed |

---

## Chapter 13 - Future Extension Points

| Extension | Description | Future Spec |
|-----------|-------------|-------------|
| Plugin Runtime | Plugin loading, unloading, lifecycle | AK0050+ |
| Local Capability | Built-in capability without plugin | AK00XX |
| Remote Capability | Capability provided by remote service | AK00XX |
| Distributed Capability | Capability spanning multiple nodes | AK00XX |
| Sandbox Runtime | Isolated execution environment | AK00XX |
| Container Runtime | Container-based capability execution | AK00XX |
| WASM Runtime | WebAssembly-based capability | AK00XX |
| Python Runtime | Python script execution capability | AK00XX |
| LLM Runtime | LLM model invocation capability | AK00XX |
| GPU Runtime | GPU-accelerated capability | AK00XX |

---

## Chapter 14 - Engineering Decisions

### Decision 1: Resolver Does Not Execute
The Resolver produces ExecutionBinding only. It never executes the capability.
**Reason:** Strict separation. Enables independent evolution of resolution and execution.

### Decision 2: ExecutionBinding is Immutable
Once created, ExecutionBinding is read-only.
**Reason:** Predictability. Executor can safely read without synchronization.

### Decision 3: Resolver is Stateless
Each Resolve() call is independent. No per-Task state persists.
**Reason:** Simplicity. Easier to test, parallelize, and distribute.

### Decision 4: Uses Value Types Only
All inputs and outputs are value types or const references. No Core Domain pointers.
**Reason:** Lifetime safety. Enables future distributed resolution.

### Decision 5: Plugin Lifetime is External
Resolver does not load, unload, or manage plugin lifetime.
**Reason:** Plugin lifecycle belongs to Plugin Runtime (future AK0050+).

### Decision 6: No Core Domain Modification
Resolver never creates, modifies, or destroys Core Domain objects.
**Reason:** Core Domain freeze. Task remains structural description.

### Decision 7: Failure Does Not Modify Task
When resolution fails, Resolver reports failure. Does not set Task to kFailed.
**Reason:** Task owns its lifecycle state. Runtime orchestrator manages transitions.

---

## Chapter 15 - Conformance Criteria

### Architecture
- Resolver exists only in Runtime layer
- Core Domain (AK0011-AK0016) remains unchanged
- AK0021 and AK0022 remain unchanged
- No new KernelObjectState values introduced

### Ownership
- Resolver does not own Session, Workflow, or Task
- Resolver does not own Plugin instances
- Resolver uses value types, not Core Domain pointers

### Resolution
- Resolver resolves TaskExecutionDescriptor to ExecutionBinding
- Resolver never executes the capability
- Resolution is stateless
- ExecutionBinding is immutable after creation

### API
- ICapabilityResolver exposes only Resolve, Supports, Validate, Initialize, Shutdown
- No LoadPlugin, UnloadPlugin, CreatePlugin, DestroyPlugin
- No Execute() or scheduling methods

### Boundary
- Resolver does not modify Task state or lifecycle
- ExecutionBinding is not stored inside Task
- Resolution failure does not set Task to kFailed
- No dependency on Scheduler, Plugin, or Core Domain internals

---

## Chapter 16 - Final Architecture Statement

AK0023 introduces the third Runtime component.

With AK0021, AK0022, and AK0023, the Runtime now possesses a complete execution pipeline:

`
Core Domain -> Scheduler -> Executor -> Capability Resolver -> ExecutionBinding -> (future) Plugin Runtime
`

The Capability Resolver completes the Runtime execution pipeline while remaining independent of future Plugin, Context, and Memory layers.

---

*End of AK0023 - Capability Resolution Specification*