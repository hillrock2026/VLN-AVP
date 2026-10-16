// ============================================================
// Agent Kernel �?Task
// ============================================================
// Task is a structural execution description object. It is
// the smallest schedulable entity in the Kernel and the leaf
// of the three-tier object hierarchy (Session→Workflow→Task).
//
// Task describes execution intent. It does NOT contain
// execution mechanism.
//
// Task owns (CR-001A):
// - Identity (TaskID via TypedKernelObject)
// - Lifecycle state (KernelObjectState)
// - Metadata (KernelMetadata)
// - Input/output contract (TaskContract)
// - Dependency metadata (TaskDependency �?read-only)
// - Execution intent descriptor (TaskExecutionDescriptor �?immutable)
//
// Task does NOT own:
// - function pointers, callables, callbacks
// - executor, plugin, tool instances
// - runtime objects
//
// Dependencies are descriptive metadata only. The authoritative
// dependency topology is WorkflowGraph (owned by Workflow).
// Dependency creation happens through Workflow::DefineDependency().
// Task reads dependencies; Workflow mutates them.
//
// TaskExecutionDescriptor is set during construction via any Core-authorized
// construction path and is immutable for the lifetime of the Task.
//
// Task is owned by Workflow and is the leaf Kernel Object.
//
// Foundation Layer: inherits TypedKernelObject<Task, TaskID>,
// composes ObserverRegistry, KernelMetadata, TaskContract,
// and TaskExecutionDescriptor.
// ============================================================

#pragma once

#include <memory>
#include <vector>

#include <agent_kernel/object_id.hpp>
#include <agent_kernel/state.hpp>
#include <agent_kernel/relationship.hpp>
#include <agent_kernel/foundation/kernel_object.hpp>
#include <agent_kernel/foundation/kernel_observer.hpp>
#include <agent_kernel/foundation/kernel_metadata.hpp>
#include <agent_kernel/foundation/kernel_contracts.hpp>
#include <agent_kernel/task/task_contract.hpp>
#include <agent_kernel/task/task_dependency.hpp>
#include <agent_kernel/task/task_execution_descriptor.hpp>

namespace ak {

// ============================================================
// ITaskObserver
// ============================================================
class ITaskObserver : public KernelObserver {
public:
    ~ITaskObserver() noexcept override = default;

    virtual void OnCompleted(TaskID id) = 0;
    virtual void OnFailed(TaskID id, const char* message) = 0;
    virtual void OnProgress(TaskID id, double progress) = 0;
};

// ============================================================
// Task �?structural execution description object
// ============================================================
class Task : public TypedKernelObject<Task, TaskID> {
public:
    // -- Lifecycle --
    Task() = delete;
    Task(TaskID id, WorkflowID parentWorkflow);
    Task(TaskID id, WorkflowID parentWorkflow, const TaskExecutionDescriptor& descriptor);
    ~Task() noexcept override;

    Task(const Task&) = delete;
    Task& operator=(const Task&) = delete;
    Task(Task&&) noexcept;
    Task& operator=(Task&&) noexcept;

    // -- Identity (from TypedKernelObject) --
    using TypedKernelObject::GetID;
    using TypedKernelObject::GetIDValue;

    // -- Parent --
    [[nodiscard]] WorkflowID GetParentWorkflowID() const noexcept;

    // -- State --
    [[nodiscard]] KernelObjectState GetState() const noexcept;

    // -- Metadata --
    [[nodiscard]] const KernelMetadata& GetMetadata() const noexcept;
    void SetMetadata(const KernelMetadata& metadata);

    // -- Contract (set during construction via TaskBuilder) --
    [[nodiscard]] const TaskContract& GetContract() const noexcept;

    // -- Execution descriptor (immutable after construction) --
    [[nodiscard]] const TaskExecutionDescriptor&
        GetExecutionDescriptor() const noexcept;

    // -- Lifecycle operations --
    void Initialize();
    void Complete();
    void Reset();
    void Destroy();

    // -- Dependency metadata (read-only �?see Workflow::DefineDependency) --
    [[nodiscard]] const std::vector<TaskDependency>&
        GetDependencies() const noexcept;

    // -- Observation --
    void AttachObserver(std::shared_ptr<ITaskObserver> observer);
    void DetachObserver(ITaskObserver* observer);

private:
    WorkflowID parentWorkflow_;
    KernelObjectState state_;
    KernelMetadata metadata_;
    TaskContract contract_;
    TaskExecutionDescriptor executionDescriptor_;
    std::vector<TaskDependency> dependencies_;

    // Workflow synchronizes dependency metadata via friend access.
    friend class Workflow;

    ObserverRegistry observerRegistry_;
};

}  // namespace ak
