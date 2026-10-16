// ============================================================
// Agent Kernel - IExecutor
// ============================================================
// Executor interface - Runtime execution engine.
//
// The Executor receives SchedulingDecision from the Scheduler
// and performs execution by resolving TaskExecutionDescriptor
// and dispatching to the capability runtime.
//
// Design principles:
// - Uses Runtime value objects (no Core Domain pointers)
// - Does not own Core Domain objects
// - Does not schedule tasks (Scheduler responsibility)
// - Capability resolution is abstract (future AK0030+)
//
// AK0022 Chapter 8 - Executor API Contract
// ============================================================

#pragma once

#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <agent_kernel/object_id.hpp>
#include <agent_kernel/scheduler/i_scheduler.hpp>
#include <agent_kernel/executor/execution_request.hpp>
#include <agent_kernel/executor/execution_result.hpp>
#include <agent_kernel/executor/executor_configuration.hpp>

namespace ak {

// Forward declarations
class ExecutionContext;

// ============================================================
// IExecutor
// ============================================================
class IExecutor {
public:
    virtual ~IExecutor() noexcept = default;

    // Submit a scheduling decision for execution.
    // Returns immediately. Completion is reported via
    // Scheduler notification.
    virtual void Submit(SchedulingDecision decision) = 0;

    // Cancel execution of a specific task.
    virtual void Cancel(TaskID task) = 0;

    // Configure the executor with new configuration.
    virtual void Configure(ExecutorConfiguration config) = 0;

    // Lifecycle control.
    virtual void Initialize() = 0;
    virtual void Shutdown() = 0;
};

}  // namespace ak
