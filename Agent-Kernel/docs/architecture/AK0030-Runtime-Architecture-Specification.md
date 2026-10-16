# AK0030 — Runtime Architecture Specification

**Document ID:** AK0030
**Version:** Revision 2

**Status:** Accepted
**Layer:** Runtime Layer
**Depends On:** AK0011, AK0012, AK0013, AK0014, AK0015, AK0016, ADD0001, AK0021, AK0022, AK0023

Chapter 1 — Introduction
1.1 Purpose

This document specifies the Runtime Layer architecture of Agent Kernel.

The Runtime Layer is responsible for executing workflows defined by the Core Foundation while preserving all architectural ownership boundaries established by Core Foundation Revision 2.

This specification defines:

* Runtime responsibilities
* Runtime component model
* Runtime execution flow
* Runtime lifecycle authority
* Runtime API contracts
* Runtime conformance requirements

This document does not redefine any Core Foundation ownership rules.

1.2 Scope

This specification applies to:

* Scheduler
* Executor
* CapabilityResolver
* Runtime
* EventBus

This specification does not redefine:

* Session
* Workflow
* Task
* WorkflowGraph
* Lifecycle State
* KernelObjectState

Those are defined by AK0011–AK0016.

1.3 Runtime Position
                                   Application
                                           │
                                 Runtime Layer
                                           │
 ┌─────────────────────────────────────┐
 │ Runtime                                                        │
 │ Scheduler                                                                 │
 │ Executor                                                                   │
 │ Capability Resolver                                                   │
 │ Event Bus                                                                 │
 │                                                       │
 └─────────────────────────────────────┘
                                            │
                                Core Foundation
                                            │
                        Session → Workflow → Task

Runtime executes.

Core owns.

Chapter 2 — Runtime Design Principles

The following principles are mandatory.

RP-1 Runtime Owns Execution Authority

Runtime determines when execution occurs.

Core never executes work.

RP-2 Core Owns Lifecycle State

Runtime requests lifecycle transitions.

Core performs lifecycle transitions.

Only Core stores lifecycle state.

RP-3 Runtime Never Owns Domain Objects

Runtime never owns:

* Session
* Workflow
* Task

Ownership remains entirely inside Core.

RP-4 Runtime Never Owns Workflow Topology

WorkflowGraph remains the only topology authority.

Runtime only queries topology.

RP-5 Runtime Never Owns TaskExecutionDescriptor

Task owns:

TaskExecutionDescriptor

Runtime obtains descriptors only through:

Task::GetExecutionDescriptor()

No Runtime descriptor cache is permitted.

RP-6 Runtime Is Stateless

Runtime does not persist execution state beyond an execution cycle.

Persistent state belongs to Core.

RP-7 ExecutionResult Belongs Only to Runtime

ExecutionResult is Runtime evidence.

It must never be stored inside:

* Session
* Workflow
* Task

RP-8 Components Have Single Responsibility

Each Runtime component performs one responsibility only.

Chapter 3 — Runtime Component Model

The Runtime object model consists of the following components:

Runtime Layer

├── Runtime
├── Scheduler
├── Executor
├── CapabilityResolver
├── 
└── EventBus

3.1 Runtime

Runtime is the single Runtime root object. It receives a Session by reference and orchestrates execution through its owned components.

Runtime owns:
  - Scheduler
  - Executor
  - CapabilityResolver
  - EventBus

Runtime responsibilities:

* Receive Session& and drive the execution loop
* Call Scheduler to obtain next TaskID
* Look up Task via Workflow::FindTask()
* Dispatch Task to Executor with descriptor from Task::GetExecutionDescriptor()
* Evaluate ExecutionResult
* Request lifecycle transitions through Core lifecycle APIs (Task::Complete(), Workflow::Complete(), Session shutdown)
* Publish Runtime events via EventBus

Runtime shall never:

* Own Session, Workflow, Task, or TaskExecutionDescriptor
* Mutate KernelObjectState directly (only through public Core APIs)
* Store ExecutionResult beyond the current execution cycle

3.2 Scheduler

Responsibilities:

* Read WorkflowGraph
* Select next Task
* Produce SchedulingDecision

Scheduler shall never:

* Execute capability
* Complete Task
* Complete Workflow
* Publish events

3.3 Executor

Responsibilities:

* Execute one Task
* Invoke Capability
* Return ExecutionResult

Executor shall never:

* Schedule Task
* Complete Task
* Mutate Workflow
* Publish lifecycle events

3.4 CapabilityResolver

Responsibilities:

Resolve

TaskExecutionDescriptor

to

Capability Binding

CapabilityResolver never executes capabilities.

3.5 EventBus

Responsibilities:

* Publish events
* Deliver events

EventBus never mutates lifecycle state.

Runtime coordinates all component interaction. No separate dispatcher object exists.

Chapter 4 — Runtime Execution Model

Runtime executes the following sequence.

Runtime
↓
Scheduler
↓
TaskID
↓
Workflow::FindTask()
↓
Task
↓
TaskExecutionDescriptor
↓
Executor
↓
CapabilityResolver
↓
Capability
↓
ExecutionResult
↓
Runtime Evaluation
↓
Task Complete()
↓
Workflow Complete()
↓
EventBus
↓
Next Schedule

The execution descriptor must always originate from:

Task::GetExecutionDescriptor()
Chapter 4 — Scheduling

Scheduler consumes only:

* WorkflowGraph
* Workflow status
* Dependency information

Scheduler returns:

SchedulingDecision

containing:

TaskID

Scheduling Status

Scheduler shall never return a TaskExecutionDescriptor.

Chapter 4 — Execution

Executor receives:

TaskExecutionDescriptor

Executor performs:

Resolve Capability

Invoke Capability

Collect Result

Return ExecutionResult

Executor shall never:

mutate Workflow
mutate Session
call Complete()
schedule Task

Chapter 4 — Capability Resolution

CapabilityResolver performs:

Descriptor
↓
Capability Binding
↓
Capability Instance

Capability execution belongs exclusively to Executor.

Chapter 4 — Event Publication

EventBus publishes Runtime events.

Typical events:

TaskStarted

TaskCompleted

TaskFailed

WorkflowCompleted

WorkflowFailed

Events never mutate Core state.

Chapter 4 — Lifecycle Authority

Lifecycle authority belongs to Runtime.

Lifecycle state belongs to Core.

Runtime evaluates:

ExecutionResult

Runtime requests:

Task::Complete()

Workflow::Complete()

Session::Complete()

Core validates and performs the state transition.

Chapter 4 — Runtime State Machine

Runtime itself follows:

Idle
↓
Scheduling
↓
Executing
↓
Evaluating
↓
Publishing
↓
Idle

This is Runtime state only.

It is independent from KernelObjectState.

Chapter 4 — Runtime Extension Points

Supported extension points include:

Capability Providers

Capability Resolver Strategies

Logging

Metrics

Tracing

Event Subscribers

Unsupported extension points include:

* Workflow ownership
* Task ownership
* Lifecycle semantics
* WorkflowGraph ownership

Chapter 4 — Runtime API Contract

The Runtime Layer exposes the following logical APIs.

Run()

Execute()

Dispatch()

Schedule()

Resolve()

Publish()

API behavior shall conform to the separation of responsibilities defined in this specification.

Chapter 4 — Runtime Conformance Requirements

A conforming Runtime implementation shall satisfy all of the following:

✓ Runtime owns execution authority.

✓ Core owns lifecycle state.

✓ Scheduler never executes.

✓ Executor never schedules.

✓ CapabilityResolver never executes capabilities.

✓ EventBus never mutates lifecycle state.

✓ Runtime never owns WorkflowGraph.

✓ Runtime never owns TaskExecutionDescriptor.

✓ Runtime never stores ExecutionResult inside Core objects.

✓ Runtime obtains descriptors only through Task ownership.

✓ Runtime requests lifecycle operations through public Core APIs.

Violation of any requirement constitutes Runtime non-conformance.

Chapter 15 — Runtime Validation Requirements

Runtime shall be validated through the Runtime Architecture Validation Prototype (AVP0030).

The minimum validation scenarios shall include:

Scenario		Objective
AVP0030-A	Single Task execution
AVP0030-B	Capability failure handling
AVP0030-C	Sequential workflow execution
AVP0030-D	Parallel workflow scheduling
AVP0030-E	Lifecycle authority validation
AVP0030-F	Event publication validation
AVP0030-G	Runtime boundary validation
AVP0030-H	Descriptor ownership validation
AVP0030-I	Scheduler/Executor separation
AVP0030-J	Full Runtime execution cycle

The Runtime Layer shall not be accepted until all mandatory AVP0030 scenarios have passed the Architecture Acceptance Review.
