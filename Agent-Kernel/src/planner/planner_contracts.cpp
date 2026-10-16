// ============================================================
// Agent Kernel - PlannerContracts (Planner boundary)
// ============================================================
// Implementation of the two Planner-owned Agent-facing contracts.
// ============================================================

#include <agent_kernel/planner/planner_contracts.hpp>

#include <agent_kernel/planner/planner.hpp>

namespace ak::planner {

PlanningService& PlannerAgentContract::Planning() noexcept {
    return planner_->planning_service_;
}

const PlanningService& PlannerAgentContract::Planning() const noexcept {
    return planner_->planning_service_;
}

LifecycleParticipationService& PlannerLifecycleContract::Lifecycle() noexcept {
    return planner_->lifecycle_service_;
}

const LifecycleParticipationService& PlannerLifecycleContract::Lifecycle() const noexcept {
    return planner_->lifecycle_service_;
}

}  // namespace ak::planner
