// ============================================================
// Agent Kernel - MemoryLifecycle (Memory boundary)
// ============================================================
// Implementation of the Memory-owned lifecycle representation.
// Memory initiates every transition; the Foundation validator
// only validates the normative rule.
// ============================================================

#include <agent_kernel/memory/memory_lifecycle.hpp>

namespace ak::memory {

MemoryResult MemoryLifecycle::Transition(
    std::initializer_list<MemoryLifecycleState> required_from,
    MemoryLifecycleState target) {
    bool from_permitted = false;
    for (MemoryLifecycleState candidate : required_from) {
        if (state_ == candidate) {
            from_permitted = true;
            break;
        }
    }
    if (!from_permitted) {
        return {MemoryResultStatus::kRejected,
                "lifecycle transition is not permitted from the current state"};
    }

    const ak::TransitionResult validated = validator_.Validate(
        ToLifecycleState(state_), ToLifecycleState(target));
    if (validated.Rejected()) {
        return {MemoryResultStatus::kRejected, validated.message};
    }

    state_ = target;
    return {MemoryResultStatus::kSuccess, "lifecycle transition accepted"};
}

MemoryResult MemoryLifecycle::Initialize() {
    return Transition({MemoryLifecycleState::kRegistered},
                      MemoryLifecycleState::kInitializing);
}

MemoryResult MemoryLifecycle::Activate() {
    return Transition({MemoryLifecycleState::kInitializing},
                      MemoryLifecycleState::kActive);
}

MemoryResult MemoryLifecycle::Suspend() {
    return Transition({MemoryLifecycleState::kActive},
                      MemoryLifecycleState::kSuspended);
}

MemoryResult MemoryLifecycle::Resume() {
    return Transition({MemoryLifecycleState::kSuspended},
                      MemoryLifecycleState::kActive);
}

MemoryResult MemoryLifecycle::Terminate() {
    return Transition({MemoryLifecycleState::kActive,
                       MemoryLifecycleState::kSuspended},
                      MemoryLifecycleState::kTerminating);
}

MemoryResult MemoryLifecycle::Dispose() {
    return Transition({MemoryLifecycleState::kTerminating},
                      MemoryLifecycleState::kDisposed);
}

}  // namespace ak::memory