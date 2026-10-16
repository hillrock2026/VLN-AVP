// ============================================================
// Agent Kernel - ContextLifecycle (Context boundary)
// ============================================================
// Context-owned lifecycle representation of a Context Object.
//
// P1-IS004 scope (Chapter 10 - Lifecycle, Chapter 27):
// - Context owns the complete architectural lifecycle of every
//   Context Object; this machine is the per-object lifecycle
//   authority inside the Context boundary.
// - Only the normative transitions are permitted:
//       Created -> Initialized
//       Initialized -> Active
//       Active -> Updated
//       Updated -> Active
//       Active -> Released
//       Updated -> Released
// - Released is terminal and irreversible.
// - The Foundation validator only validates the normative rule;
//   it is not the lifecycle authority.
// - Lifecycle remains independent from Agent, Memory, Planner,
//   Tool, Session, Workflow, Task, and Runtime lifecycle.
//
// NON-responsibilities:
// - ContextLifecycle is not a Runtime lifecycle and references
//   no Runtime type.
// - It does not mutate Agent, Memory, Planner, Tool, or Runtime
//   lifecycle.
// ============================================================

#pragma once

#include <cstdint>
#include <initializer_list>
#include <string_view>

#include <agent_kernel/context/context_result.hpp>
#include <agent_kernel/context/context_state.hpp>

namespace ak::context {

class ContextLifecycle {
public:
    ContextLifecycle() = default;

    // -- Context-owned transition operations --
    // Created -> Initialized.
    [[nodiscard]] ContextResult Initialize();
    // Initialized -> Active.
    [[nodiscard]] ContextResult Activate();
    // Active -> Updated (controlled evolution begins).
    [[nodiscard]] ContextResult BeginUpdate();
    // Updated -> Active (controlled evolution completes).
    [[nodiscard]] ContextResult CompleteUpdate();
    // Active/Updated -> Released (terminal, irreversible).
    [[nodiscard]] ContextResult Release();

    [[nodiscard]] ContextLifecycleState GetState() const noexcept {
        return state_;
    }

    [[nodiscard]] std::string_view GetStateName() const noexcept {
        return ContextLifecycleStateName(state_);
    }

private:
    [[nodiscard]] ContextResult Transition(
        std::initializer_list<ContextLifecycleState> required_from,
        ContextLifecycleState target);

    ContextLifecycleState state_ = ContextLifecycleState::kCreated;
    ak::LifecycleTransitionValidator validator_{&ContextLifecycleTransitionRule};
};

}  // namespace ak::context
