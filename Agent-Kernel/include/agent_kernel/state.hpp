// ============================================================
// Agent Kernel — State
// ============================================================
// Common lifecycle state model for all Kernel Objects.
//
// Every Kernel Object follows the same state machine defined
// in AK0011 Chapter 6. Illegal transitions throw ak::StateError.
//
// This header defines the KernelObjectState enumeration and
// state transition utilities.
// ============================================================

#pragma once

#include <cstdint>

namespace ak {

// ============================================================
// KernelObjectState — unified state enumeration
// ============================================================
enum class KernelObjectState : std::uint8_t {
    kCreated = 0,
    kInitialized,
    kReady,
    kRunning,
    kSuspended,
    kCompleted,
    kFailed,
    kDestroyed
};

// ============================================================
// Utility functions
// ============================================================

// Returns true if the state allows transition to the target.
[[nodiscard]] bool IsValidTransition(
    KernelObjectState from,
    KernelObjectState to) noexcept;

// Returns true if the state is a terminal state
// (Completed, Failed, Destroyed).
[[nodiscard]] bool IsTerminal(KernelObjectState state) noexcept;

}  // namespace ak
