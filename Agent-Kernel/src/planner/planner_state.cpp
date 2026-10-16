// ============================================================
// Agent Kernel - PlannerState (Planner boundary)
// ============================================================
// Implementation of the Planner lifecycle/operational state
// models and their normative transition validation.
// ============================================================

#include <agent_kernel/planner/planner_state.hpp>

#include <cstdint>

namespace ak::planner {

bool PlannerLifecycleTransitionRule(std::uint8_t from, std::uint8_t to) noexcept {
    return IsLegalPlannerLifecycleTransition(
        static_cast<PlannerLifecycleState>(from),
        static_cast<PlannerLifecycleState>(to));
}

ak::TransitionResult ValidatePlannerLifecycleTransition(
    PlannerLifecycleState from, PlannerLifecycleState to) noexcept {
    static const ak::LifecycleTransitionValidator validator(
        &PlannerLifecycleTransitionRule);
    return validator.Validate(ToLifecycleState(from), ToLifecycleState(to));
}

}  // namespace ak::planner
