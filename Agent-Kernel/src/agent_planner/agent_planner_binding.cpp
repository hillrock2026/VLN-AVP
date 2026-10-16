// ============================================================
// Agent Kernel - AgentPlannerBinding (Agent-owned production
// invocation surface)
// ============================================================
// Implementation of the AgentPlannerBinding: the production
// invocation path Agent -> Binding -> Contracts -> Planner,
// including the post-Terminated refusal gate (P1-IS005 Rev5.1
// Chapter 15.3). The gate reads only Planner root accessors and
// never invokes a Planner Service before refusing.
// ============================================================

#include <agent_kernel/agent_planner/agent_planner_binding.hpp>

namespace ak::agent {
namespace pl = ak::planner;

AgentPlannerBinding::AgentPlannerBinding(pl::Planner& planner,
                                         pl::PlannerAgentContract& capability,
                                         pl::PlannerLifecycleContract& lifecycle) noexcept
    : planner_(&planner), capability_(&capability), lifecycle_(&lifecycle) {}

pl::PlannerAgentContract& AgentPlannerBinding::Capability() noexcept {
    return *capability_;
}

const pl::PlannerAgentContract& AgentPlannerBinding::Capability() const noexcept {
    return *capability_;
}

pl::PlannerLifecycleContract& AgentPlannerBinding::Lifecycle() noexcept {
    return *lifecycle_;
}

const pl::PlannerLifecycleContract& AgentPlannerBinding::Lifecycle() const noexcept {
    return *lifecycle_;
}

pl::PlanningAcceptance AgentPlannerBinding::Submit(const pl::PlanningRequest& request) {
    if (planner_->GetLifecycleState() == pl::PlannerLifecycleState::kTerminated) {
        return {pl::PlanningAcceptanceStatus::kUnavailable, "planner terminated",
                request.request_id, request.session_id};
    }
    return capability_->Planning().Submit(request);
}

pl::PlanningCompletionResult AgentPlannerBinding::CompletePlanningExchange(
    const pl::PlanningRequestId& request_id) {
    if (planner_->GetLifecycleState() == pl::PlannerLifecycleState::kTerminated) {
        return {pl::PlanningCompletionStatus::kRejectedTerminated,
                "planner terminated", pl::PlanningResult{}};
    }
    return capability_->Planning().CompletePlanningExchange(request_id);
}

pl::PlannerLifecycleResult AgentPlannerBinding::Initialize() {
    if (planner_->GetLifecycleState() == pl::PlannerLifecycleState::kTerminated) {
        return {pl::PlannerLifecycleResultStatus::kUnavailable,
                "planner terminated", pl::PlannerLifecycleState::kTerminated};
    }
    return lifecycle_->Lifecycle().Initialize();
}

pl::PlannerLifecycleResult AgentPlannerBinding::Activate() {
    if (planner_->GetLifecycleState() == pl::PlannerLifecycleState::kTerminated) {
        return {pl::PlannerLifecycleResultStatus::kUnavailable,
                "planner terminated", pl::PlannerLifecycleState::kTerminated};
    }
    return lifecycle_->Lifecycle().Activate();
}

pl::PlannerLifecycleResult AgentPlannerBinding::Suspend() {
    if (planner_->GetLifecycleState() == pl::PlannerLifecycleState::kTerminated) {
        return {pl::PlannerLifecycleResultStatus::kUnavailable,
                "planner terminated", pl::PlannerLifecycleState::kTerminated};
    }
    return lifecycle_->Lifecycle().Suspend();
}

pl::PlannerLifecycleResult AgentPlannerBinding::Resume() {
    if (planner_->GetLifecycleState() == pl::PlannerLifecycleState::kTerminated) {
        return {pl::PlannerLifecycleResultStatus::kUnavailable,
                "planner terminated", pl::PlannerLifecycleState::kTerminated};
    }
    return lifecycle_->Lifecycle().Resume();
}

pl::PlannerLifecycleResult AgentPlannerBinding::Terminate() {
    if (planner_->GetLifecycleState() == pl::PlannerLifecycleState::kTerminated) {
        return {pl::PlannerLifecycleResultStatus::kUnavailable,
                "planner terminated", pl::PlannerLifecycleState::kTerminated};
    }
    return lifecycle_->Lifecycle().Terminate();
}

pl::PlannerOperationalState AgentPlannerBinding::GetOperationalState() const noexcept {
    // Reads the Planner root accessor directly; does NOT delegate
    // to the Inspection Service (MIN-001: inspection is
    // unavailable after Terminated).
    return planner_->GetOperationalState();
}

}  // namespace ak::agent
