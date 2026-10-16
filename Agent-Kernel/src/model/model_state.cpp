// ============================================================
// Agent Kernel - ModelState implementation (Model boundary)
// ============================================================
// Implementation of the Model lifecycle state model and its
// normative transition validation (P1-IS008 Rev1.0 Chapter 10).
// ============================================================

#include <agent_kernel/model/model_state.hpp>

#include <cstdint>

namespace ak::model {

bool ModelLifecycleTransitionRule(std::uint8_t from, std::uint8_t to) noexcept {
    return IsLegalModelLifecycleTransition(
        static_cast<ModelLifecycleState>(from),
        static_cast<ModelLifecycleState>(to));
}

ak::TransitionResult ValidateModelLifecycleTransition(
    ModelLifecycleState from, ModelLifecycleState to) noexcept {
    static const ak::LifecycleTransitionValidator validator(
        &ModelLifecycleTransitionRule);
    return validator.Validate(ToLifecycleState(from), ToLifecycleState(to));
}

}  // namespace ak::model
