// ============================================================
// Agent Kernel - AgentState (Agent boundary)
// ============================================================
// Implementation of the single Agent architectural state model
// and its normative transition validation.
// ============================================================

#include <agent_kernel/agent/agent_state.hpp>

#include <cstdint>

namespace ak::agent {

bool AgentStateTransitionRule(std::uint8_t from, std::uint8_t to) noexcept {
    return IsLegalAgentTransition(static_cast<AgentState>(from),
                                  static_cast<AgentState>(to));
}

ak::TransitionResult ValidateAgentTransition(AgentState from,
                                             AgentState to) noexcept {
    // The Foundation validator only validates; the Agent owns
    // and initiates every transition.
    static const ak::LifecycleTransitionValidator validator(
        &AgentStateTransitionRule);
    return validator.Validate(ToLifecycleState(from), ToLifecycleState(to));
}

}  // namespace ak::agent
