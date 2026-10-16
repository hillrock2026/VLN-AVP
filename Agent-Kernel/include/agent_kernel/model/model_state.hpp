// ============================================================
// Agent Kernel - ModelState (Model boundary)
// ============================================================
// P1-IS008 Rev1.0 Chapter 10 - Model lifecycle.
//
// Model lifecycle is distinct from Agent lifecycle and from the
// inference-operation lifecycle. A minimal implementation may
// retain only the states required by actual behavior:
//   Uninitialized -> Ready (initialization)
//   Uninitialized -> Unavailable (provider unavailable)
//   Ready -> Shutdown
//   Unavailable -> Shutdown
//
// Initialization establishes Model configuration/provider
// binding; it does not establish Agent or Runtime lifecycle.
// Shutdown releases only Model-owned resources and never
// terminates Agent, Runtime, Tool, Planner, Prompt, Memory, or
// Context (Chapter 10).
//
// Failure during inference returns to the reusable Ready state
// when supported (Chapter 10); a failed inference does not
// transition the Model state machine.
//
// NON-responsibilities:
// - These states are Model-owned; no other subsystem owns or
//   drives them.
// ============================================================

#pragma once

#include <compare>
#include <cstdint>
#include <string_view>

#include <agent_kernel/foundation/kernel_lifecycle.hpp>

namespace ak::model {

// ------------------------------------------------------------
// Model lifecycle state model (P1-IS008 Rev1.0 Chapter 10)
// ------------------------------------------------------------
enum class ModelLifecycleState : std::uint8_t {
    kUninitialized = 0,
    kReady,
    kUnavailable,
    kShutdown
};

[[nodiscard]] constexpr std::string_view ModelLifecycleStateName(
    ModelLifecycleState state) noexcept {
    switch (state) {
        case ModelLifecycleState::kUninitialized:
            return "Uninitialized";
        case ModelLifecycleState::kReady:
            return "Ready";
        case ModelLifecycleState::kUnavailable:
            return "Unavailable";
        case ModelLifecycleState::kShutdown:
            return "Shutdown";
    }
    return "Unknown";
}

[[nodiscard]] constexpr std::uint8_t ModelLifecycleStateCode(
    ModelLifecycleState state) noexcept {
    return static_cast<std::uint8_t>(state);
}

[[nodiscard]] inline ak::LifecycleState ToLifecycleState(
    ModelLifecycleState state) noexcept {
    return ak::LifecycleState(ModelLifecycleStateCode(state));
}

// ------------------------------------------------------------
// Normative lifecycle transitions (P1-IS008 Rev1.0 Chapter 10)
// ------------------------------------------------------------
[[nodiscard]] constexpr bool IsLegalModelLifecycleTransition(
    ModelLifecycleState from, ModelLifecycleState to) noexcept {
    switch (from) {
        case ModelLifecycleState::kUninitialized:
            return to == ModelLifecycleState::kReady ||
                   to == ModelLifecycleState::kUnavailable;
        case ModelLifecycleState::kReady:
            return to == ModelLifecycleState::kShutdown;
        case ModelLifecycleState::kUnavailable:
            return to == ModelLifecycleState::kShutdown;
        case ModelLifecycleState::kShutdown:
            return false;
    }
    return false;
}

// Foundation-neutral rule adapter (owner-defined rule).
[[nodiscard]] bool ModelLifecycleTransitionRule(std::uint8_t from,
                                                std::uint8_t to) noexcept;

// Validates a requested lifecycle transition. The Foundation
// validator only validates; the Model owns and initiates every
// transition.
[[nodiscard]] ak::TransitionResult ValidateModelLifecycleTransition(
    ModelLifecycleState from, ModelLifecycleState to) noexcept;

}  // namespace ak::model
