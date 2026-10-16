// ============================================================
// Agent Kernel - ContextOperationalStateMachine (Context boundary)
// ============================================================
// Context-owned operational-state representation of a Context
// Object.
//
// P1-IS004 scope (Chapter 11 - Operational State, Chapter 27):
// - Context exclusively owns operational state and mutates it
//   through its own transition operations.
// - Operational state answers how the Context Object currently
//   participates in intelligent execution; it is a distinct
//   dimension from lifecycle.
// - Only the normative transitions are permitted:
//       Uninitialized -> Ready
//       Ready -> Active
//       Active -> Updating
//       Updating -> Active
//       Active -> Released
// - Released is terminal and irreversible.
//
// NON-responsibilities:
// - The machine is not a lifecycle model and is not owned by
//   Agent, Memory, or Runtime.
// - Runtime remains unaware of Context operational state.
// ============================================================

#pragma once

#include <cstdint>
#include <initializer_list>
#include <string_view>

#include <agent_kernel/context/context_result.hpp>
#include <agent_kernel/context/context_state.hpp>

namespace ak::context {

class ContextOperationalStateMachine {
public:
    ContextOperationalStateMachine() = default;

    // -- Context-owned transition operations --
    // Uninitialized -> Ready.
    [[nodiscard]] ContextResult ToReady();
    // Ready -> Active.
    [[nodiscard]] ContextResult ToActive();
    // Active -> Updating (controlled modification begins).
    [[nodiscard]] ContextResult ToUpdating();
    // Updating -> Active (controlled modification completes).
    [[nodiscard]] ContextResult ToActiveAfterUpdate();
    // Active -> Released (terminal, irreversible).
    [[nodiscard]] ContextResult ToReleased();

    [[nodiscard]] ContextOperationalState GetState() const noexcept {
        return state_;
    }

    [[nodiscard]] std::string_view GetStateName() const noexcept {
        return ContextOperationalStateName(state_);
    }

private:
    [[nodiscard]] ContextResult Transition(
        std::initializer_list<ContextOperationalState> required_from,
        ContextOperationalState target);

    ContextOperationalState state_ = ContextOperationalState::kUninitialized;
    ak::LifecycleTransitionValidator validator_{&ContextOperationalTransitionRule};
};

}  // namespace ak::context
