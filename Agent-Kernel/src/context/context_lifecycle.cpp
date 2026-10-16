// ============================================================
// Agent Kernel - ContextLifecycle (Context boundary)
// ============================================================
// Implementation of the Context-owned lifecycle representation
// of a Context Object. Context initiates every transition; the
// Foundation validator only validates the normative rule.
// ============================================================

#include <agent_kernel/context/context_lifecycle.hpp>

namespace ak::context {

ContextResult ContextLifecycle::Transition(
    std::initializer_list<ContextLifecycleState> required_from,
    ContextLifecycleState target) {
    bool from_permitted = false;
    for (ContextLifecycleState candidate : required_from) {
        if (state_ == candidate) {
            from_permitted = true;
            break;
        }
    }
    if (!from_permitted) {
        return {ContextResultStatus::kRejected,
                "lifecycle transition is not permitted from the current state"};
    }

    const ak::TransitionResult validated = validator_.Validate(
        ToLifecycleState(state_), ToLifecycleState(target));
    if (validated.Rejected()) {
        return {ContextResultStatus::kRejected, validated.message};
    }

    state_ = target;
    return {ContextResultStatus::kSuccess, "lifecycle transition accepted"};
}

ContextResult ContextLifecycle::Initialize() {
    return Transition({ContextLifecycleState::kCreated},
                      ContextLifecycleState::kInitialized);
}

ContextResult ContextLifecycle::Activate() {
    return Transition({ContextLifecycleState::kInitialized},
                      ContextLifecycleState::kActive);
}

ContextResult ContextLifecycle::BeginUpdate() {
    return Transition({ContextLifecycleState::kActive},
                      ContextLifecycleState::kUpdated);
}

ContextResult ContextLifecycle::CompleteUpdate() {
    return Transition({ContextLifecycleState::kUpdated},
                      ContextLifecycleState::kActive);
}

ContextResult ContextLifecycle::Release() {
    return Transition({ContextLifecycleState::kActive,
                       ContextLifecycleState::kUpdated},
                      ContextLifecycleState::kReleased);
}

}  // namespace ak::context
