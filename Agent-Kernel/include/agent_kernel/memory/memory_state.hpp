// ============================================================
// Agent Kernel - MemoryState (Memory boundary)
// ============================================================
// Memory lifecycle and Memory operational state: two separate
// architectural state models.
//
// P1-IS003 scope (Chapter 8 - Lifecycle, Chapter 9 - State
// Model, Chapter 16.1):
// - Lifecycle answers "does Memory architecturally exist?";
//   operational state answers "what service availability is
//   currently provided?".
// - The two models SHALL NOT be collapsed into one state
//   machine.
//
// Lifecycle (normative):
//   Registered -> Initializing -> Active <-> Suspended
//   Active/Suspended -> Terminating -> Disposed (terminal)
//
// Operational (normative):
//   Unavailable -> Ready -> Available <-> Busy
//   Available/Busy -> Degraded -> Available
//   Available/Degraded -> Unavailable
//
// NON-responsibilities:
// - These models are Memory-owned. The Foundation validator
//   only validates; it cannot initiate a transition.
// - Agent may inspect but not mutate Memory operational state.
// - Runtime remains unaware of Memory state.
// ============================================================

#pragma once

#include <cstdint>
#include <string_view>

#include <agent_kernel/foundation/kernel_lifecycle.hpp>

namespace ak::memory {

// ------------------------------------------------------------
// Memory lifecycle state model
// ------------------------------------------------------------
enum class MemoryLifecycleState : std::uint8_t {
    kRegistered = 0,
    kInitializing,
    kActive,
    kSuspended,
    kTerminating,
    kDisposed
};

[[nodiscard]] constexpr std::string_view MemoryLifecycleStateName(
    MemoryLifecycleState state) noexcept {
    switch (state) {
        case MemoryLifecycleState::kRegistered:
            return "Registered";
        case MemoryLifecycleState::kInitializing:
            return "Initializing";
        case MemoryLifecycleState::kActive:
            return "Active";
        case MemoryLifecycleState::kSuspended:
            return "Suspended";
        case MemoryLifecycleState::kTerminating:
            return "Terminating";
        case MemoryLifecycleState::kDisposed:
            return "Disposed";
    }
    return "Unknown";
}

[[nodiscard]] constexpr std::uint8_t MemoryLifecycleStateCode(
    MemoryLifecycleState state) noexcept {
    return static_cast<std::uint8_t>(state);
}

[[nodiscard]] inline ak::LifecycleState ToLifecycleState(
    MemoryLifecycleState state) noexcept {
    return ak::LifecycleState(MemoryLifecycleStateCode(state));
}

// Normative lifecycle transitions (P1-IS003 Chapter 8.2).
[[nodiscard]] constexpr bool IsLegalMemoryLifecycleTransition(
    MemoryLifecycleState from, MemoryLifecycleState to) noexcept {
    switch (from) {
        case MemoryLifecycleState::kRegistered:
            return to == MemoryLifecycleState::kInitializing;
        case MemoryLifecycleState::kInitializing:
            return to == MemoryLifecycleState::kActive;
        case MemoryLifecycleState::kActive:
            return to == MemoryLifecycleState::kSuspended ||
                   to == MemoryLifecycleState::kTerminating;
        case MemoryLifecycleState::kSuspended:
            return to == MemoryLifecycleState::kActive ||
                   to == MemoryLifecycleState::kTerminating;
        case MemoryLifecycleState::kTerminating:
            return to == MemoryLifecycleState::kDisposed;
        case MemoryLifecycleState::kDisposed:
            return false;
    }
    return false;
}

// Foundation-neutral rule adapter.
[[nodiscard]] bool MemoryLifecycleTransitionRule(std::uint8_t from,
                                                 std::uint8_t to) noexcept;

// Validates a requested lifecycle transition. The Foundation
// validator only validates; Memory owns and initiates every
// transition.
[[nodiscard]] ak::TransitionResult ValidateMemoryLifecycleTransition(
    MemoryLifecycleState from, MemoryLifecycleState to) noexcept;

// ------------------------------------------------------------
// Memory operational state model
// ------------------------------------------------------------
enum class MemoryOperationalState : std::uint8_t {
    kUnavailable = 0,
    kReady,
    kAvailable,
    kBusy,
    kDegraded
};

[[nodiscard]] constexpr std::string_view MemoryOperationalStateName(
    MemoryOperationalState state) noexcept {
    switch (state) {
        case MemoryOperationalState::kUnavailable:
            return "Unavailable";
        case MemoryOperationalState::kReady:
            return "Ready";
        case MemoryOperationalState::kAvailable:
            return "Available";
        case MemoryOperationalState::kBusy:
            return "Busy";
        case MemoryOperationalState::kDegraded:
            return "Degraded";
    }
    return "Unknown";
}

// Normative operational transitions (P1-IS003 Chapter 9.2).
[[nodiscard]] inline ak::LifecycleState ToLifecycleState(
    MemoryOperationalState state) noexcept {
    return ak::LifecycleState(static_cast<std::uint8_t>(state));
}

[[nodiscard]] constexpr bool IsLegalMemoryOperationalTransition(
    MemoryOperationalState from, MemoryOperationalState to) noexcept {
    switch (from) {
        case MemoryOperationalState::kUnavailable:
            return to == MemoryOperationalState::kReady;
        case MemoryOperationalState::kReady:
            return to == MemoryOperationalState::kAvailable;
        case MemoryOperationalState::kAvailable:
            return to == MemoryOperationalState::kBusy ||
                   to == MemoryOperationalState::kDegraded ||
                   to == MemoryOperationalState::kUnavailable;
        case MemoryOperationalState::kBusy:
            return to == MemoryOperationalState::kAvailable ||
                   to == MemoryOperationalState::kDegraded;
        case MemoryOperationalState::kDegraded:
            return to == MemoryOperationalState::kAvailable ||
                   to == MemoryOperationalState::kUnavailable;
    }
    return false;
}

// Foundation-neutral rule adapter.
[[nodiscard]] bool MemoryOperationalTransitionRule(std::uint8_t from,
                                                   std::uint8_t to) noexcept;

// Validates a requested operational transition. Memory owns and
// initiates every transition.
[[nodiscard]] ak::TransitionResult ValidateMemoryOperationalTransition(
    MemoryOperationalState from, MemoryOperationalState to) noexcept;

}  // namespace ak::memory