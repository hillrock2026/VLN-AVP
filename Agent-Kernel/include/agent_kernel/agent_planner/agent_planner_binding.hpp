// ============================================================
// Agent Kernel - AgentPlannerBinding (Agent-owned production
// invocation surface)
// ============================================================
// P1-IS005 Rev5.1 Chapter 15; AK0044 Revision A Section 11.
//
// AgentPlannerBinding is the Agent-owned production invocation
// surface (namespace ak::agent, target agent_kernel_agent_planner).
// It is implementation infrastructure, NOT a new architectural
// subsystem, NOT a test helper, and NOT a competing contract.
//
// It holds non-owning references to the two Planner-owned
// contracts and to the Planner root (for the refusal gate). It
// does not own Planner state.
//
// Dependency direction:
//   Agent -> AgentPlannerBinding -> PlannerAgentContract /
//   PlannerLifecycleContract -> Planner -> Foundation
//
// Post-Terminated refusal gate (Chapter 15.3): every invocation
// operation evaluates the gate first; when the Planner is
// Terminated, the binding returns the deterministic refusal
// WITHOUT invoking any Planner Service.
//
// NON-responsibilities:
// - The binding never mutates Planner state and never performs
//   Runtime actions.
// ============================================================

#pragma once

#include <agent_kernel/planner/planner.hpp>
#include <agent_kernel/planner/planner_contracts.hpp>
#include <agent_kernel/planner/planner_result.hpp>
#include <agent_kernel/planner/planner_state.hpp>
#include <agent_kernel/planner/planning_request.hpp>

namespace ak::agent {

class AgentPlannerBinding {
public:
    // planner must outlive the binding; contracts must be the
    // planner's own contracts.
    AgentPlannerBinding(ak::planner::Planner& planner,
                        ak::planner::PlannerAgentContract& capability,
                        ak::planner::PlannerLifecycleContract& lifecycle) noexcept;

    // -- Contract access --
    [[nodiscard]] ak::planner::PlannerAgentContract& Capability() noexcept;
    [[nodiscard]] const ak::planner::PlannerAgentContract& Capability() const noexcept;
    [[nodiscard]] ak::planner::PlannerLifecycleContract& Lifecycle() noexcept;
    [[nodiscard]] const ak::planner::PlannerLifecycleContract& Lifecycle() const noexcept;

    // -- Agent invocation operations (production path) --
    [[nodiscard]] ak::planner::PlanningAcceptance Submit(
        const ak::planner::PlanningRequest& request);
    [[nodiscard]] ak::planner::PlanningCompletionResult CompletePlanningExchange(
        const ak::planner::PlanningRequestId& request_id);
    [[nodiscard]] ak::planner::PlannerLifecycleResult Initialize();
    [[nodiscard]] ak::planner::PlannerLifecycleResult Activate();
    [[nodiscard]] ak::planner::PlannerLifecycleResult Suspend();
    [[nodiscard]] ak::planner::PlannerLifecycleResult Resume();
    [[nodiscard]] ak::planner::PlannerLifecycleResult Terminate();
    // Reads the Planner root accessor directly; does NOT
    // delegate to the Inspection Service (MIN-001: inspection
    // is unavailable after Terminated).
    [[nodiscard]] ak::planner::PlannerOperationalState GetOperationalState() const noexcept;

private:
    ak::planner::Planner* planner_ = nullptr;
    ak::planner::PlannerAgentContract* capability_ = nullptr;
    ak::planner::PlannerLifecycleContract* lifecycle_ = nullptr;
};

}  // namespace ak::agent
