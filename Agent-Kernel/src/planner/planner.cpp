// ============================================================
// Agent Kernel - Planner (Planner boundary)
// ============================================================
// Implementation of the Planner root object.
//
// The Planner root owns the single synchronization boundary
// (one std::mutex); every service operation and every state
// accessor serializes through it (P1-IS005 Rev5.1 Chapter 12.2).
// ============================================================

#include <agent_kernel/planner/planner.hpp>

#include <cstddef>
#include <mutex>
#include <utility>

namespace ak::planner {

Planner::Planner(PlannerIdentity identity, IPlanningEngine& engine,
                 PlannerConfiguration configuration)
    : identity_(identity),
      engine_(&engine),
      planning_service_(*this),
      lifecycle_service_(*this),
      inspection_service_(*this),
      agent_contract_(*this),
      lifecycle_contract_(*this),
      configuration_(std::move(configuration)) {}

PlannerIdentity Planner::GetIdentity() const noexcept {
    return identity_;
}

PlannerLifecycleState Planner::GetLifecycleState() const noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    return lifecycle_;
}

PlannerOperationalState Planner::GetOperationalState() const noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    return ProjectOperationalState(lifecycle_);
}

std::size_t Planner::OpenExchangeCount() const noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    return (session_ != nullptr) ? session_->OpenExchangeCount() : 0;
}

PlannerState Planner::GetState() const noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    PlannerState state;
    state.lifecycle = lifecycle_;
    state.operational = ProjectOperationalState(lifecycle_);
    state.open_exchange_count =
        (session_ != nullptr) ? session_->OpenExchangeCount() : 0;
    state.active_artifact_count = CountActiveArtifactsLocked();
    state.session_count = (session_ != nullptr) ? 1 : 0;
    return state;
}

PlannerAgentContract& Planner::AgentContract() noexcept {
    return agent_contract_;
}

const PlannerAgentContract& Planner::AgentContract() const noexcept {
    return agent_contract_;
}

PlannerLifecycleContract& Planner::LifecycleContract() noexcept {
    return lifecycle_contract_;
}

const PlannerLifecycleContract& Planner::LifecycleContract() const noexcept {
    return lifecycle_contract_;
}

PlannerInspectionService& Planner::Inspection() noexcept {
    return inspection_service_;
}

const PlannerInspectionService& Planner::Inspection() const noexcept {
    return inspection_service_;
}

PlannerExtensionBoundary& Planner::Extensions() noexcept {
    return extensions_;
}

const PlannerExtensionBoundary& Planner::Extensions() const noexcept {
    return extensions_;
}

std::size_t Planner::CountActiveArtifactsLocked() const noexcept {
    std::size_t active = 0;
    try {
        for (const auto& key : artifacts_.Enumerate()) {
            const PlanningArtifact* artifact = artifacts_.Find(key);
            if (artifact != nullptr && !artifact->IsRetired()) {
                ++active;
            }
        }
    } catch (...) {
        return 0;
    }
    return active;
}

PlanningResultId Planner::NextResultId() noexcept {
    return MakePlanningResultId(next_result_value_++);
}

PlanningArtifactId Planner::NextArtifactId() noexcept {
    return MakePlanningArtifactId(next_artifact_value_++);
}

ExecutionPlanId Planner::NextExecutionPlanId() noexcept {
    return MakeExecutionPlanId(next_execution_plan_value_++);
}

}  // namespace ak::planner
