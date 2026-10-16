// ============================================================
// Agent Kernel - AgentPlannerHost (Agent-owned production
// composition root)
// ============================================================
// Implementation of the single Phase 3 production composition
// root (P1-IS005 Rev5.1 Chapter 16.2):
//   engine_ -> planner_ -> binding_ (declaration order = init
//   order; lifetime engine_ >= planner_ >= binding_).
// ============================================================

#include <agent_kernel/agent_planner/agent_planner_host.hpp>

#include <utility>

namespace ak::agent {

AgentPlannerHost::AgentPlannerHost(ak::planner::PlannerIdentity identity,
                                   ak::planner::PlannerConfiguration configuration)
    : engine_(),
      planner_(identity, engine_, std::move(configuration)),
      binding_(planner_, planner_.AgentContract(), planner_.LifecycleContract()) {}

AgentPlannerBinding& AgentPlannerHost::Binding() noexcept {
    return binding_;
}

const AgentPlannerBinding& AgentPlannerHost::Binding() const noexcept {
    return binding_;
}

ak::planner::Planner& AgentPlannerHost::Planner() noexcept {
    return planner_;
}

const ak::planner::Planner& AgentPlannerHost::Planner() const noexcept {
    return planner_;
}

ak::planner::PlannerIdentity AgentPlannerHost::GetPlannerIdentity() const noexcept {
    return planner_.GetIdentity();
}

}  // namespace ak::agent
