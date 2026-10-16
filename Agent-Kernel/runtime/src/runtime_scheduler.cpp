#include <runtime_scheduler.h>

#include <agent_kernel/workflow/graph_algorithms.hpp>

namespace ak::runtime {

Scheduler::Scheduler() = default;
Scheduler::~Scheduler() = default;

// ============================================================
// Workflow Management
// ============================================================

void Scheduler::Attach(ak::WorkflowID workflow) {
    attachedWorkflows_.insert(workflow);
}

void Scheduler::Detach(ak::WorkflowID workflow) {
    attachedWorkflows_.erase(workflow);
}

// ============================================================
// Scheduling — Next()
// ============================================================
SchedulingDecision Scheduler::Next(const ak::WorkflowGraph& graph) {
    SchedulingDecision decision;
    decision.workflowID = ak::WorkflowID();

    if (graph.GetNodeCount() == 0) {
        decision.status = SchedulingStatus::kWorkflowCompleted;
        return decision;
    }

    auto topoOpt = ComputeTopologicalOrder(graph);
    if (!topoOpt.has_value()) {
        decision.status = SchedulingStatus::kWorkflowFailed;
        return decision;
    }

    const auto& order = topoOpt->orderedTasks;
    bool anyIncomplete = false;
    bool anyFailed = false;

    for (const auto& taskId : order) {
        if (completedTasks_.count(taskId) > 0) continue;

        if (failedTasks_.count(taskId) > 0) {
            anyFailed = true;
            continue;
        }

        anyIncomplete = true;

        if (IsRunnable(taskId, graph)) {
            decision.nextTask = taskId;
            decision.status = SchedulingStatus::kTaskReady;
            return decision;
        }
    }

    if (!anyIncomplete) {
        decision.status = SchedulingStatus::kWorkflowCompleted;
    } else if (anyFailed) {
        decision.status = SchedulingStatus::kWorkflowFailed;
    } else {
        decision.status = SchedulingStatus::kNoRunnableTask;
    }

    return decision;
}

bool Scheduler::IsRunnable(
    ak::TaskID task,
    const ak::WorkflowGraph& graph) const noexcept {

    if (completedTasks_.count(task) > 0) return false;
    if (failedTasks_.count(task) > 0) return false;

    auto predecessors = graph.GetPredecessors(task);
    for (const auto& predId : predecessors) {
        if (completedTasks_.count(predId) == 0) return false;
    }

    return true;
}

// ============================================================
// Notification
// ============================================================

void Scheduler::NotifyCompleted(ak::TaskID task) {
    completedTasks_.insert(task);
}

void Scheduler::NotifyFailed(ak::TaskID task) {
    failedTasks_.insert(task);
}

}  // namespace ak::runtime