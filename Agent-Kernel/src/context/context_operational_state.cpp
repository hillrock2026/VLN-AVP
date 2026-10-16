// ============================================================
// Agent Kernel - ContextOperationalStateMachine (Context boundary)
// ============================================================
// Implementation of the Context-owned operational-state
// representation of a Context Object. Context initiates every
// transition; the Foundation validator only validates the
// normative rule.
// ============================================================

#include <agent_kernel/context/context_operational_state.hpp>

namespace ak::context {

ContextResult ContextOperationalStateMachine::Transition(
    std::initializer_list<ContextOperationalState> required_from,
    ContextOperationalState target) {
    bool from_permitted = false;
    for (ContextOperationalState candidate : required_from) {
        if (state_ == candidate) {
            from_permitted = true;
            break;
        }
    }
    if (!from_permitted) {
        return {ContextResultStatus::kRejected,
                "operational-state transition is not permitted from the "
                "current state"};
    }

    const ak::TransitionResult validated = validator_.Validate(
        ToOperationalState(state_), ToOperationalState(target));
    if (validated.Rejected()) {
        return {ContextResultStatus::kRejected, validated.message};
    }

    state_ = target;
    return {ContextResultStatus::kSuccess, "operational-state transition accepted"};
}

ContextResult ContextOperationalStateMachine::ToReady() {
    return Transition({ContextOperationalState::kUninitialized},
                      ContextOperationalState::kReady);
}

ContextResult ContextOperationalStateMachine::ToActive() {
    return Transition({ContextOperationalState::kReady},
                      ContextOperationalState::kActive);
}

ContextResult ContextOperationalStateMachine::ToUpdating() {
    return Transition({ContextOperationalState::kActive},
                      ContextOperationalState::kUpdating);
}

ContextResult ContextOperationalStateMachine::ToActiveAfterUpdate() {
    return Transition({ContextOperationalState::kUpdating},
                      ContextOperationalState::kActive);
}

ContextResult ContextOperationalStateMachine::ToReleased() {
    return Transition({ContextOperationalState::kActive},
                      ContextOperationalState::kReleased);
}

}  // namespace ak::context
