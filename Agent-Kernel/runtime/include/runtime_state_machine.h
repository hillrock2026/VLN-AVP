#pragma once

// ============================================================
// P0R0001 — Runtime State Machine
// ============================================================
// Defines Runtime lifecycle states and state transition
// validation for the Runtime Core.
//
// P0R0001 lifecycle:
//   Created → Running → Stopped
//      ↓        ↓
//      └──→ Failed ←──┘
//
// States are single-threaded and synchronous (Revision 2).
// No concurrent state access is supported.
// ============================================================

#include <cstdint>

namespace ak::runtime {

// ============================================================
// RuntimeState — Runtime lifecycle states
// ============================================================
enum class RuntimeState : std::uint8_t {
    kCreated = 0,
    kRunning,
    kStopped,
    kFailed
};

// ============================================================
// RuntimeStateMachine
// ============================================================
class RuntimeStateMachine {
public:
    RuntimeStateMachine() noexcept;

    RuntimeStateMachine(const RuntimeStateMachine&) = delete;
    RuntimeStateMachine& operator=(const RuntimeStateMachine&) = delete;
    RuntimeStateMachine(RuntimeStateMachine&&) = delete;
    RuntimeStateMachine& operator=(RuntimeStateMachine&&) = delete;

    [[nodiscard]] RuntimeState GetState() const noexcept;
    [[nodiscard]] bool CanTransitionTo(RuntimeState target) const noexcept;
    [[nodiscard]] bool IsTerminal() const noexcept;
    [[nodiscard]] bool TransitionTo(RuntimeState target) noexcept;
    [[nodiscard]] bool Reset() noexcept;

private:
    RuntimeState state_;
    [[nodiscard]] static bool IsValidTransition(RuntimeState from, RuntimeState to) noexcept;
};

}  // namespace ak::runtime