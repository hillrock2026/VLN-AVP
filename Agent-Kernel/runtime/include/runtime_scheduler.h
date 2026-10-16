#pragma once

// ============================================================
// P0R0002 — Runtime Scheduler
// ============================================================
// The Scheduler determines which Task is eligible for execution
// according to the current Workflow execution state.
//
// Responsibilities:
// - Manage attached Workflows
// - Evaluate WorkflowGraph to identify runnable Tasks
// - Track Task completion/failure state
// - Produce SchedulingDecision objects
//
// NON-responsibilities:
// - Does NOT execute Tasks (Executor — P0R0003)
// - Does NOT resolve Capabilities (Resolver — P0R0004)
// - Does NOT publish Events (EventBus — P0R0005)
// - Does NOT modify Runtime lifecycle
//
// Conforms to AK0031 (Runtime Scheduler Specification).
// ============================================================

#include <cstdint>
#include <optional>
#include <unordered_set>

#include <agent_kernel/object_id.hpp>
#include <agent_kernel/workflow/workflow_graph.hpp>

namespace ak::runtime {

// ============================================================
// SchedulingStatus — outcome of a scheduling pass
// ============================================================
enum class SchedulingStatus : std::uint8_t {
    kTaskReady = 0,       // A runnable task was selected.
    kWorkflowCompleted,   // All tasks in the workflow have completed.
    kWorkflowFailed,      // The workflow cannot proceed (unrecoverable failure).
    kNoRunnableTask,      // No task is currently runnable (dependencies unmet).
};

// ============================================================
// SchedulingDecision — output of Scheduler::Next()
// ============================================================
struct SchedulingDecision {
    std::optional<ak::TaskID> nextTask;   // Selected runnable Task, or empty.
    ak::WorkflowID workflowID;            // Owning workflow identifier.
    SchedulingStatus status;              // Scheduling outcome.

    [[nodiscard]] bool HasTask() const noexcept {
        return nextTask.has_value();
    }
};

// ============================================================
// Scheduler — Runtime component (Revision 2, P0R0002)
// ============================================================
class Scheduler {
public:
    Scheduler();
    ~Scheduler();

    Scheduler(const Scheduler&) = delete;
    Scheduler& operator=(const Scheduler&) = delete;
    Scheduler(Scheduler&&) = delete;
    Scheduler& operator=(Scheduler&&) = delete;

    // ---- Workflow Management ----
    void Attach(ak::WorkflowID workflow);
    void Detach(ak::WorkflowID workflow);

    // ---- Scheduling ----
    [[nodiscard]] SchedulingDecision Next(const ak::WorkflowGraph& graph);

    // ---- Notification ----
    void NotifyCompleted(ak::TaskID task);
    void NotifyFailed(ak::TaskID task);

private:
    std::unordered_set<ak::WorkflowID> attachedWorkflows_;
    std::unordered_set<ak::TaskID> completedTasks_;
    std::unordered_set<ak::TaskID> failedTasks_;

    [[nodiscard]] bool IsRunnable(
        ak::TaskID task,
        const ak::WorkflowGraph& graph) const noexcept;
};

}  // namespace ak::runtime