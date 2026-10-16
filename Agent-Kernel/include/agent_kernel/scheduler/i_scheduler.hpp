// ============================================================
// Agent Kernel - IScheduler
// ============================================================
// Scheduler interface - Runtime decision engine.
//
// The Scheduler determines WHEN and WHAT can execute.
// It does NOT execute tasks (Executor responsibility).
//
// Design principles:
// - Uses IDs only (no Task*, no Workflow*)
// - Does not own Core Domain objects
// - WorkflowGraph is the only topology authority
// - Scheduling policy is replaceable
//
// AK0021 Chapter 7 - Scheduler API Contract
// ============================================================

#pragma once

#include <memory>
#include <optional>
#include <vector>

#include <agent_kernel/object_id.hpp>

namespace ak {

// ============================================================
// SchedulingStatus
// ============================================================
enum class SchedulingStatus : std::uint8_t {
    kTaskReady,          // A runnable task was selected
    kWorkflowCompleted,  // All tasks in workflow completed
    kWorkflowFailed,     // A task failed, workflow cannot proceed
    kIdle,               // No runnable tasks at this time
    kWaiting             // Waiting for external dependencies
};

// ============================================================
// SchedulingItem
// ============================================================
struct SchedulingItem {
    TaskID taskID;
    WorkflowID workflowID;
    int priority = 0;
    // Timestamp enqueueTime;  // Reserved for future use
};

// ============================================================
// SchedulingDecision
// ============================================================
struct SchedulingDecision {
    std::optional<TaskID> nextTask;  // Empty if no runnable task
    WorkflowID workflowID;
    SchedulingStatus status;
};

// ============================================================
// IScheduler
// ============================================================
class IScheduler {
public:
    virtual ~IScheduler() noexcept = default;

    // Attach a workflow to the scheduler.
    virtual void Attach(WorkflowID workflow) = 0;

    // Detach a workflow. Releases scheduler-internal state.
    virtual void Detach(WorkflowID workflow) = 0;

    // Return the next task to execute, or empty if none available.
    [[nodiscard]] virtual SchedulingDecision Next() = 0;

    // Notify the scheduler that a task completed successfully.
    virtual void NotifyCompleted(TaskID task) = 0;

    // Notify the scheduler that a task failed.
    virtual void NotifyFailed(TaskID task) = 0;
};

}  // namespace ak
