// ============================================================
// Agent Kernel - ContextState (Context boundary)
// ============================================================
// Context lifecycle and Context operational state: two separate
// architectural state models.
//
// P1-IS004 scope (Chapter 10 - Lifecycle, Chapter 11 -
// Operational State, Chapter 27):
// - Lifecycle answers "when the Context Object exists";
//   operational state answers "how the Context Object currently
//   participates in intelligent execution".
// - The two models SHALL NOT be collapsed into one state
//   machine; they are distinct types.
// - Context owns both models; the Foundation validator only
//   validates the normative rules and cannot initiate a
//   transition.
//
// Lifecycle (normative, P1-IS004 Chapter 10.2):
//   Created -> Initialized -> Active <-> Updated
//   Active/Updated -> Released (terminal)
//
// Operational (normative, P1-IS004 Chapter 11.2):
//   Uninitialized -> Ready -> Active <-> Updating
//   Active -> Released (terminal)
//
// NON-responsibilities:
// - These models are Context-owned; no other subsystem owns or
//   drives them.
// - Runtime remains unaware of Context lifecycle and state.
// ============================================================

#pragma once

#include <cstdint>
#include <string_view>

#include <agent_kernel/foundation/kernel_lifecycle.hpp>

namespace ak::context {

// ------------------------------------------------------------
// Context lifecycle state model
// ------------------------------------------------------------
enum class ContextLifecycleState : std::uint8_t {
    kCreated = 0,
    kInitialized,
    kActive,
    kUpdated,
    kReleased
};

[[nodiscard]] constexpr std::string_view ContextLifecycleStateName(
    ContextLifecycleState state) noexcept {
    switch (state) {
        case ContextLifecycleState::kCreated:
            return "Created";
        case ContextLifecycleState::kInitialized:
            return "Initialized";
        case ContextLifecycleState::kActive:
            return "Active";
        case ContextLifecycleState::kUpdated:
            return "Updated";
        case ContextLifecycleState::kReleased:
            return "Released";
    }
    return "Unknown";
}

[[nodiscard]] constexpr std::uint8_t ContextLifecycleStateCode(
    ContextLifecycleState state) noexcept {
    return static_cast<std::uint8_t>(state);
}

[[nodiscard]] inline ak::LifecycleState ToLifecycleState(
    ContextLifecycleState state) noexcept {
    return ak::LifecycleState(ContextLifecycleStateCode(state));
}

// Normative lifecycle transitions (P1-IS004 Chapter 10.4).
[[nodiscard]] constexpr bool IsLegalContextLifecycleTransition(
    ContextLifecycleState from, ContextLifecycleState to) noexcept {
    switch (from) {
        case ContextLifecycleState::kCreated:
            return to == ContextLifecycleState::kInitialized;
        case ContextLifecycleState::kInitialized:
            return to == ContextLifecycleState::kActive;
        case ContextLifecycleState::kActive:
            return to == ContextLifecycleState::kUpdated ||
                   to == ContextLifecycleState::kReleased;
        case ContextLifecycleState::kUpdated:
            return to == ContextLifecycleState::kActive ||
                   to == ContextLifecycleState::kReleased;
        case ContextLifecycleState::kReleased:
            return false;
    }
    return false;
}

// Foundation-neutral rule adapter.
[[nodiscard]] bool ContextLifecycleTransitionRule(std::uint8_t from,
                                                  std::uint8_t to) noexcept;

// Validates a requested lifecycle transition. The Foundation
// validator only validates; Context owns and initiates every
// transition.
[[nodiscard]] ak::TransitionResult ValidateContextLifecycleTransition(
    ContextLifecycleState from, ContextLifecycleState to) noexcept;

// ------------------------------------------------------------
// Context operational state model
// ------------------------------------------------------------
enum class ContextOperationalState : std::uint8_t {
    kUninitialized = 0,
    kReady,
    kActive,
    kUpdating,
    kReleased
};

[[nodiscard]] constexpr std::string_view ContextOperationalStateName(
    ContextOperationalState state) noexcept {
    switch (state) {
        case ContextOperationalState::kUninitialized:
            return "Uninitialized";
        case ContextOperationalState::kReady:
            return "Ready";
        case ContextOperationalState::kActive:
            return "Active";
        case ContextOperationalState::kUpdating:
            return "Updating";
        case ContextOperationalState::kReleased:
            return "Released";
    }
    return "Unknown";
}

[[nodiscard]] constexpr std::uint8_t ContextOperationalStateCode(
    ContextOperationalState state) noexcept {
    return static_cast<std::uint8_t>(state);
}

[[nodiscard]] inline ak::LifecycleState ToOperationalState(
    ContextOperationalState state) noexcept {
    return ak::LifecycleState(ContextOperationalStateCode(state));
}

// Normative operational transitions (P1-IS004 Chapter 11.4).
[[nodiscard]] constexpr bool IsLegalContextOperationalTransition(
    ContextOperationalState from, ContextOperationalState to) noexcept {
    switch (from) {
        case ContextOperationalState::kUninitialized:
            return to == ContextOperationalState::kReady;
        case ContextOperationalState::kReady:
            return to == ContextOperationalState::kActive;
        case ContextOperationalState::kActive:
            return to == ContextOperationalState::kUpdating ||
                   to == ContextOperationalState::kReleased;
        case ContextOperationalState::kUpdating:
            return to == ContextOperationalState::kActive;
        case ContextOperationalState::kReleased:
            return false;
    }
    return false;
}

// Foundation-neutral rule adapter.
[[nodiscard]] bool ContextOperationalTransitionRule(std::uint8_t from,
                                                    std::uint8_t to) noexcept;

// Validates a requested operational transition. Context owns
// and initiates every transition.
[[nodiscard]] ak::TransitionResult ValidateContextOperationalTransition(
    ContextOperationalState from, ContextOperationalState to) noexcept;

}  // namespace ak::context
