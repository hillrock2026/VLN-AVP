// ============================================================
// Agent Kernel - ContextState (Context boundary)
// ============================================================
// Implementation of the two Context state models and their
// normative transition validation.
// ============================================================

#include <agent_kernel/context/context_state.hpp>

#include <cstdint>

namespace ak::context {

bool ContextLifecycleTransitionRule(std::uint8_t from, std::uint8_t to) noexcept {
    return IsLegalContextLifecycleTransition(
        static_cast<ContextLifecycleState>(from),
        static_cast<ContextLifecycleState>(to));
}

ak::TransitionResult ValidateContextLifecycleTransition(
    ContextLifecycleState from, ContextLifecycleState to) noexcept {
    static const ak::LifecycleTransitionValidator validator(
        &ContextLifecycleTransitionRule);
    return validator.Validate(ToLifecycleState(from), ToLifecycleState(to));
}

bool ContextOperationalTransitionRule(std::uint8_t from,
                                      std::uint8_t to) noexcept {
    return IsLegalContextOperationalTransition(
        static_cast<ContextOperationalState>(from),
        static_cast<ContextOperationalState>(to));
}

ak::TransitionResult ValidateContextOperationalTransition(
    ContextOperationalState from, ContextOperationalState to) noexcept {
    static const ak::LifecycleTransitionValidator validator(
        &ContextOperationalTransitionRule);
    return validator.Validate(ToOperationalState(from), ToOperationalState(to));
}

}  // namespace ak::context
