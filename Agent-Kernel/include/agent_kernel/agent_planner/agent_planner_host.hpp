// ============================================================
// Agent Kernel - AgentPlannerHost (Agent-owned production
// composition root)
// ============================================================
// P1-IS005 Rev5.1 Chapter 16; AK0044 Revision A Section 11.
//
// AgentPlannerHost is the single production composition root:
//   Agent -> AgentPlannerHost -> AgentPlannerBinding ->
//   Contracts -> Planner -> Foundation
//
// Member order is normative (declaration order = init order):
//   ImmediatePlanningEngine engine_;  // owned production engine
//   Planner planner_;                 // owned; holds engine_ reference
//   AgentPlannerBinding binding_;     // owned; views planner_ and
//                                     // its contracts
//
// Lifetime: engine_ >= planner_ >= binding_. The host SHALL be
// destroyed after the Agent stops invoking the binding.
//
// NON-responsibilities:
// - The host performs no Runtime action and is not a second
//   composition root; no other production composition path is
//   authorized for Phase 3.
// ============================================================

#pragma once

#include <agent_kernel/agent_planner/agent_planner_binding.hpp>
#include <agent_kernel/planner/planner.hpp>
#include <agent_kernel/planner/planning_engine.hpp>

namespace ak::agent {

class AgentPlannerHost {
public:
    explicit AgentPlannerHost(ak::planner::PlannerIdentity identity,
                              ak::planner::PlannerConfiguration configuration = {});
    AgentPlannerHost(const AgentPlannerHost&) = delete;
    AgentPlannerHost& operator=(const AgentPlannerHost&) = delete;

    // -- Agent-owned production surface --
    [[nodiscard]] AgentPlannerBinding& Binding() noexcept;
    [[nodiscard]] const AgentPlannerBinding& Binding() const noexcept;

    // -- Composition access (lifetime/ownership inspection) --
    [[nodiscard]] ak::planner::Planner& Planner() noexcept;
    [[nodiscard]] const ak::planner::Planner& Planner() const noexcept;
    [[nodiscard]] ak::planner::PlannerIdentity GetPlannerIdentity() const noexcept;

private:
    // member order is normative (declaration order = init order)
    ak::planner::ImmediatePlanningEngine engine_;  // owned production engine
    ak::planner::Planner planner_;                 // owned; holds engine_ reference
    AgentPlannerBinding binding_;                  // owned; views planner_ and its contracts
};

}  // namespace ak::agent
