// ============================================================
// Agent Kernel - MemoryOperationalStateMachine (Memory boundary)
// ============================================================
// Memory-owned operational-state representation.
//
// P1-IS003 scope (Chapter 9 - State Model, Chapter 16.1):
// - Memory exclusively owns operational state and mutates it
//   through its own transition operations.
// - Agent may inspect and coordinate based on the state but
//   may not mutate it.
// - Runtime remains unaware of Memory operational state.
// - Availability semantics are carried by this model; they are
//   not redefined by lifecycle state.
//
// NON-responsibilities:
// - The machine is not a lifecycle model.
// - A provider failure contributes to Memory-owned transitions
//   only; the provider never mutates this state directly.
// ============================================================

#pragma once

#include <cstdint>
#include <initializer_list>
#include <string_view>

#include <agent_kernel/memory/memory_result.hpp>
#include <agent_kernel/memory/memory_state.hpp>

namespace ak::memory {

class MemoryOperationalStateMachine {
public:
    MemoryOperationalStateMachine() = default;

    // -- Memory-owned transition operations --
    // Unavailable -> Ready.
    [[nodiscard]] MemoryResult ToReady();
    // Ready -> Available.
    [[nodiscard]] MemoryResult ToAvailable();
    // Available -> Busy (consistency preserved).
    [[nodiscard]] MemoryResult ToBusy();
    // Available/Busy -> Degraded (reduced but contract-
    // preserving availability).
    [[nodiscard]] MemoryResult ToDegraded();
    // Available/Degraded -> Unavailable.
    [[nodiscard]] MemoryResult ToUnavailable();

    [[nodiscard]] MemoryOperationalState GetState() const noexcept {
        return state_;
    }

    [[nodiscard]] std::string_view GetStateName() const noexcept {
        return MemoryOperationalStateName(state_);
    }

private:
    [[nodiscard]] MemoryResult Transition(
        std::initializer_list<MemoryOperationalState> required_from,
        MemoryOperationalState target);

    MemoryOperationalState state_ = MemoryOperationalState::kUnavailable;
    ak::LifecycleTransitionValidator validator_{&MemoryOperationalTransitionRule};
};

}  // namespace ak::memory