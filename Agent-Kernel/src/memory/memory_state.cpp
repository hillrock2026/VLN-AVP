// ============================================================
// Agent Kernel - MemoryState (Memory boundary)
// ============================================================
// Implementation of the two Memory state models and their
// normative transition validation.
// ============================================================

#include <agent_kernel/memory/memory_state.hpp>

#include <cstdint>

namespace ak::memory {

bool MemoryLifecycleTransitionRule(std::uint8_t from, std::uint8_t to) noexcept {
    return IsLegalMemoryLifecycleTransition(
        static_cast<MemoryLifecycleState>(from),
        static_cast<MemoryLifecycleState>(to));
}

ak::TransitionResult ValidateMemoryLifecycleTransition(
    MemoryLifecycleState from, MemoryLifecycleState to) noexcept {
    static const ak::LifecycleTransitionValidator validator(
        &MemoryLifecycleTransitionRule);
    return validator.Validate(ToLifecycleState(from), ToLifecycleState(to));
}

bool MemoryOperationalTransitionRule(std::uint8_t from, std::uint8_t to) noexcept {
    return IsLegalMemoryOperationalTransition(
        static_cast<MemoryOperationalState>(from),
        static_cast<MemoryOperationalState>(to));
}

ak::TransitionResult ValidateMemoryOperationalTransition(
    MemoryOperationalState from, MemoryOperationalState to) noexcept {
    static const ak::LifecycleTransitionValidator validator(
        &MemoryOperationalTransitionRule);
    return validator.Validate(ToLifecycleState(from), ToLifecycleState(to));
}

}  // namespace ak::memory