// ============================================================
// Agent Kernel - PlanningEngine (Planner boundary)
// ============================================================
// Implementation of the deterministic production planning
// engine.
// ============================================================

#include <agent_kernel/planner/planning_engine.hpp>

namespace ak::planner {

bool ImmediatePlanningEngine::HasOutcome(const PlannerSessionId&,
                                         const PlanningRequestId&) const noexcept {
    // Deterministic production default: the terminal outcome is
    // available at the first completion attempt.
    return true;
}

PlanningOutcome ImmediatePlanningEngine::Outcome(const PlannerSessionId&,
                                                 const PlanningRequest& request) noexcept {
    PlanningOutcome outcome;
    outcome.status = PlanningOutcomeStatus::kSuccess;
    outcome.metadata.version = 1;
    outcome.metadata.strategy = "immediate";
    outcome.execution_plan_steps.push_back(request.goal);
    outcome.artifact_payload = request.goal;
    for (const auto& constraint : request.constraints) {
        outcome.artifact_payload += "; ";
        outcome.artifact_payload += constraint;
    }
    outcome.message = "planning completed";
    return outcome;
}

}  // namespace ak::planner
