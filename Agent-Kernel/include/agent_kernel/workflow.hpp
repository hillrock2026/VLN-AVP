// ============================================================
// Agent Kernel 鈥?Workflow
// ============================================================
// Workflow represents one executable orchestration.
//
// Responsibilities (AK0011 搂3.3, AK0015):
// - Owns a DAG of Tasks via WorkflowGraph (topology)
// - Owns Task objects via TaskRegistry (ownership)
// - Validates task graph structure (delegated to WorkflowGraph)
// - Exposes observability through IWorkflowObserver
//
// Workflow is owned by Session and owns Tasks.
// Workflow stores only the parent SessionID 鈥?no parent pointer.
//
// Foundation Layer: inherits TypedKernelObject<Workflow, WorkflowID>,
// composes TaskRegistry, WorkflowGraph, ObserverRegistry,
// KernelMetadata, and WorkflowConfiguration.
//
// Workflow does NOT execute Tasks, schedule them, or run graph
// algorithms internally. Those belong to Scheduler and Executor.
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
#include <agent_kernel/workflow/workflow_graph.hpp>
#include <agent_kernel/workflow/task_registry.hpp>
#include <agent_kernel/workflow/workflow_configuration.hpp>
#include <agent_kernel/task/task_execution_descriptor.hpp>

namespace ak {

// ============================================================
// IWorkflowObserver
// ============================================================
class IWorkflowObserver : public KernelObserver {
public:
    ~IWorkflowObserver() noexcept override = default;

    virtual void OnTaskCreated(WorkflowID workflowId,
                               TaskID taskId) = 0;
    virtual void OnTaskCompleted(WorkflowID workflowId,
                                 TaskID taskId) = 0;
    virtual void OnTaskFailed(WorkflowID workflowId,
                              TaskID taskId,
                              const char* message) = 0;
};

// ============================================================
// Workflow 鈥?structural container for executable Tasks
// ============================================================
class Workflow : public TypedKernelObject<Workflow, WorkflowID> {
public:
    // -- Lifecycle --
    Workflow() = delete;
    Workflow(WorkflowID id, SessionID parentSession,
             WorkflowConfiguration config);
    ~Workflow() noexcept override;

    Workflow(const Workflow&) = delete;
    Workflow& operator=(const Workflow&) = delete;
    Workflow(Workflow&&) noexcept;
    Workflow& operator=(Workflow&&) noexcept;

    // -- Identity (from TypedKernelObject) --
    using TypedKernelObject::GetID;
    using TypedKernelObject::GetIDValue;

    // -- Parent (SessionID only 鈥?no parent pointer) --
    [[nodiscard]] SessionID GetParentSessionID() const noexcept;

    // -- State --
    [[nodiscard]] KernelObjectState GetState() const noexcept;

    // -- Metadata --
    [[nodiscard]] const KernelMetadata& GetMetadata() const noexcept;
    void SetMetadata(const KernelMetadata& metadata);

    // -- Configuration --
    [[nodiscard]] const WorkflowConfiguration& GetConfiguration() const noexcept;

    // -- Lifecycle operations --
    void Initialize();
    void Activate();
    void Complete();
    void Start();
    void Cancel();
    void Destroy();

    // -- Task management --
    TaskID AddTask();
    TaskID AddTask(const TaskExecutionDescriptor& descriptor);
    void RemoveTask(TaskID id);
    [[nodiscard]] Task* FindTask(TaskID id) const noexcept;
    [[nodiscard]] bool HasTask(TaskID id) const noexcept;
    [[nodiscard]] std::size_t GetTaskCount() const noexcept;

    // -- Topology --
    void DefineDependency(TaskID from, TaskID to);
    bool Validate();
    [[nodiscard]] const WorkflowGraph& Graph() const noexcept;

    // -- Registry access --
    [[nodiscard]] TaskRegistry& Tasks();
    [[nodiscard]] const TaskRegistry& Tasks() const;

    // -- Observation --
    void AttachObserver(std::shared_ptr<IWorkflowObserver> observer);
    void DetachObserver(IWorkflowObserver* observer);

private:
    SessionID parentSession_;
    KernelObjectState state_;
    KernelMetadata metadata_;
    WorkflowConfiguration configuration_;
    TaskRegistry taskRegistry_;
    WorkflowGraph graph_;
    ObserverRegistry observerRegistry_;
};

}  // namespace ak
