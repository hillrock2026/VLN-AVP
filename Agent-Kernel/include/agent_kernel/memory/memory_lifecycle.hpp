// ============================================================
// Agent Kernel - MemoryLifecycle (Memory boundary)
// ============================================================
// Memory-owned lifecycle representation.
//
// P1-IS003 scope (Chapter 8 - Lifecycle, Chapter 16.1):
// - Memory owns its lifecycle state and initiates every
//   transition.
// - Agent requests lifecycle participation; it cannot write
//   lifecycle state directly.
// - The Foundation validator only validates the normative
//   transition rule; it is not the lifecycle authority.
//
// NON-responsibilities:
// - MemoryLifecycle is not a Runtime lifecycle and references
//   no Runtime type.
// - It does not mutate Agent, Context, Planner, Tool, or
//   Runtime lifecycle.
// ============================================================

#pragma once

#include <cstdint>
#include <initializer_list>

#include <agent_kernel/memory/memory_result.hpp>
#include <agent_kernel/memory/memory_state.hpp>

namespace ak::memory {

class MemoryLifecycle {
public:
    MemoryLifecycle() = default;

    // -- Memory-owned transition operations --
    // Registered -> Initializing.
    [[nodiscard]] MemoryResult Initialize();
    // Initializing -> Active.
    [[nodiscard]] MemoryResult Activate();
    // Active -> Suspended (reversible).
    [[nodiscard]] MemoryResult Suspend();
    // Suspended -> Active.
    [[nodiscard]] MemoryResult Resume();
    // Active/Suspended -> Terminating.
    [[nodiscard]] MemoryResult Terminate();
    // Terminating -> Disposed (terminal).
    [[nodiscard]] MemoryResult Dispose();

    [[nodiscard]] MemoryLifecycleState GetState() const noexcept {
        return state_;
    }

    [[nodiscard]] std::string_view GetStateName() const noexcept {
        return MemoryLifecycleStateName(state_);
    }

private:
    [[nodiscard]] MemoryResult Transition(
        std::initializer_list<MemoryLifecycleState> required_from,
        MemoryLifecycleState target);

    MemoryLifecycleState state_ = MemoryLifecycleState::kRegistered;
    ak::LifecycleTransitionValidator validator_{&MemoryLifecycleTransitionRule};
};

}  // namespace ak::memory