// ============================================================
// Agent Kernel — TaskBuilder
// ============================================================
// Lightweight builder for constructing Task instances.
//
// TaskBuilder configures structural properties only:
// - Identity (TaskID)
// - Parent (WorkflowID)
// - Human-readable name
// - Input/output contract (TaskContract)
// - Execution requirement (TaskExecutionDescriptor)
//
// Dependencies are NOT configured through TaskBuilder.
// Dependency creation happens through Workflow::DefineDependency(),
// which synchronizes both WorkflowGraph edges and
// TaskDependency metadata.
//
// TaskBuilder does NOT configure:
// - Executor, Scheduler, Runtime
// - Thread, tool, agent
// - Callback, lambda, function pointer
// ============================================================

#pragma once

#include <memory>
#include <string>
#include <optional>

#include <agent_kernel/object_id.hpp>
#include <agent_kernel/task/task_contract.hpp>
#include <agent_kernel/task/task_execution_descriptor.hpp>

namespace ak {

// Forward declaration
class Task;

// ============================================================
// TaskBuilder
// ============================================================
class TaskBuilder {
public:
    TaskBuilder() noexcept = default;

    // -- Identity --
    TaskBuilder& WithID(TaskID id) noexcept;
    TaskBuilder& WithParentWorkflow(WorkflowID workflowId) noexcept;
    TaskBuilder& WithName(const std::string& name);

    // -- Contract --
    TaskBuilder& WithContract(const TaskContract& contract);

    // -- Execution descriptor --
    TaskBuilder& WithExecutionDescriptor(
        const TaskExecutionDescriptor& descriptor);

    // -- Build --
    [[nodiscard]] std::unique_ptr<Task> Build();

private:
    std::optional<TaskID> id_;
    std::optional<WorkflowID> parentWorkflow_;
    std::string name_;
    TaskContract contract_;
    TaskExecutionDescriptor executionDescriptor_;
};

}  // namespace ak
