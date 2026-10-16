// ============================================================
// Agent Kernel - AgentState (Agent boundary)
// ============================================================
// Single externally visible Agent architectural state model.
//
// P1-IS002 scope (Chapter 6 - Agent State, Chapter 7 - Agent
// Lifecycle):
// - Exactly ONE architectural state model is externally
//   visible: Uninitialized / Ready / Coordinating / Supervising
//   / Suspended / Terminated (AK0041 Chapter 5.3).
// - The lifecycle phases (AK0041 Chapter 4.4 / P1-IS002
//   Chapter 7.2) map onto this same state model; the lifecycle
//   is the transition-validated state machine over it.
// - Internal implementation substates are permitted but SHALL
//   NOT redefine or contradict the externally visible states.
//
// NON-responsibilities:
// - The state model is Agent-owned. The Runtime cannot modify
//   Agent state and Agent state does not redefine Runtime
//   execution state (AK0041 SP-3 / SP-4).
// - AgentState is not a Runtime lifecycle state.
// ============================================================

#pragma once

#include <cstdint>
#include <string_view>

#include <agent_kernel/foundation/kernel_lifecycle.hpp>

namespace ak::agent {

// The single externally visible Agent architectural state model.
enum class AgentState : std::uint8_t {
    kUninitialized = 0,
    kReady,
    kCoordinating,
    kSupervising,
    kSuspended,
    kTerminated
};

// Human-readable name of an architectural state.
[[nodiscard]] constexpr std::string_view AgentStateName(AgentState state) noexcept {
    switch (state) {
        case AgentState::kUninitialized:
            return "Uninitialized";
        case AgentState::kReady:
            return "Ready";
        case AgentState::kCoordinating:
            return "Coordinating";
        case AgentState::kSupervising:
            return "Supervising";
        case AgentState::kSuspended:
            return "Suspended";
        case AgentState::kTerminated:
            return "Terminated";
    }
    return "Unknown";
}

// Numeric code used for Foundation-neutral lifecycle validation.
[[nodiscard]] constexpr std::uint8_t AgentStateCode(AgentState state) noexcept {
    return static_cast<std::uint8_t>(state);
}

// Neutral Foundation state value for the Agent-owned state.
[[nodiscard]] inline ak::LifecycleState ToLifecycleState(AgentState state) noexcept {
    return ak::LifecycleState(AgentStateCode(state));
}

// Normative transition model (AK0041 Chapter 4.5 / Chapter 5.5,
// P1-IS002 Chapter 7.2):
//
//   Uninitialized -> Ready -> Coordinating -> Supervising
//   Supervising -> Coordinating (adaptation)
//   Supervising -> Suspended -> Ready -> Terminated
//
// Any transition not listed here is illegal and SHALL be
// rejected by the Agent with a clear error result.
[[nodiscard]] constexpr bool IsLegalAgentTransition(AgentState from,
                                                    AgentState to) noexcept {
    switch (from) {
        case AgentState::kUninitialized:
            return to == AgentState::kReady;
        case AgentState::kReady:
            return to == AgentState::kCoordinating ||
                   to == AgentState::kTerminated;
        case AgentState::kCoordinating:
            return to == AgentState::kSupervising;
        case AgentState::kSupervising:
            return to == AgentState::kCoordinating ||
                   to == AgentState::kSuspended;
        case AgentState::kSuspended:
            return to == AgentState::kReady;
        case AgentState::kTerminated:
            return false;
    }
    return false;
}

// Foundation-neutral rule adapter (uint8-based transition rule).
[[nodiscard]] bool AgentStateTransitionRule(std::uint8_t from,
                                            std::uint8_t to) noexcept;

// Validates a requested Agent state transition. The Foundation
// validator only validates; the Agent owns and initiates every
// transition.
[[nodiscard]] ak::TransitionResult ValidateAgentTransition(AgentState from,
                                                           AgentState to) noexcept;

}  // namespace ak::agent
