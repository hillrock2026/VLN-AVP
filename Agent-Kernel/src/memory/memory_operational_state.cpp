// ============================================================
// Agent Kernel - MemoryOperationalStateMachine (Memory boundary)
// ============================================================
// Implementation of the Memory-owned operational state model.
// Memory exclusively mutates this state.
// ============================================================

#include <agent_kernel/memory/memory_operational_state.hpp>

namespace ak::memory {

MemoryResult MemoryOperationalStateMachine::Transition(
    std::initializer_list<MemoryOperationalState> required_from,
    MemoryOperationalState target) {
    bool from_permitted = false;
    for (MemoryOperationalState candidate : required_from) {
        if (state_ == candidate) {
            from_permitted = true;
            break;
        }
    }
    if (!from_permitted) {
        return {MemoryResultStatus::kRejected,
                "operational transition is not permitted from the current state"};
    }

    const ak::TransitionResult validated = validator_.Validate(
        ToLifecycleState(state_), ToLifecycleState(target));
    if (validated.Rejected()) {
        return {MemoryResultStatus::kRejected, validated.message};
    }

    state_ = target;
    return {MemoryResultStatus::kSuccess, "operational transition accepted"};
}

MemoryResult MemoryOperationalStateMachine::ToReady() {
    return Transition({MemoryOperationalState::kUnavailable},
                      MemoryOperationalState::kReady);
}

MemoryResult MemoryOperationalStateMachine::ToAvailable() {
    return Transition({MemoryOperationalState::kReady,
                       MemoryOperationalState::kBusy,
                       MemoryOperationalState::kDegraded},
                      MemoryOperationalState::kAvailable);
}

MemoryResult MemoryOperationalStateMachine::ToBusy() {
    return Transition({MemoryOperationalState::kAvailable},
                      MemoryOperationalState::kBusy);
}

MemoryResult MemoryOperationalStateMachine::ToDegraded() {
    return Transition({MemoryOperationalState::kAvailable,
                       MemoryOperationalState::kBusy},
                      MemoryOperationalState::kDegraded);
}

MemoryResult MemoryOperationalStateMachine::ToUnavailable() {
    return Transition({MemoryOperationalState::kAvailable,
                       MemoryOperationalState::kDegraded},
                      MemoryOperationalState::kUnavailable);
}

}  // namespace ak::memory