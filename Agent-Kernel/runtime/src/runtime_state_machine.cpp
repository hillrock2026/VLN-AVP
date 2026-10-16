#include <runtime_state_machine.h>

namespace ak::runtime {

RuntimeStateMachine::RuntimeStateMachine() noexcept
    : state_(RuntimeState::kCreated) {}

RuntimeState RuntimeStateMachine::GetState() const noexcept {
    return state_;
}

bool RuntimeStateMachine::CanTransitionTo(RuntimeState target) const noexcept {
    return IsValidTransition(state_, target);
}

bool RuntimeStateMachine::IsTerminal() const noexcept {
    return state_ == RuntimeState::kStopped || state_ == RuntimeState::kFailed;
}

bool RuntimeStateMachine::TransitionTo(RuntimeState target) noexcept {
    if (!IsValidTransition(state_, target)) return false;
    state_ = target;
    return true;
}

bool RuntimeStateMachine::Reset() noexcept {
    if (!IsTerminal()) return false;
    state_ = RuntimeState::kCreated;
    return true;
}

bool RuntimeStateMachine::IsValidTransition(RuntimeState from, RuntimeState to) noexcept {
    switch (from) {
        case RuntimeState::kCreated:
            return to == RuntimeState::kRunning || to == RuntimeState::kFailed;
        case RuntimeState::kRunning:
            return to == RuntimeState::kStopped || to == RuntimeState::kFailed;
        case RuntimeState::kStopped:
        case RuntimeState::kFailed:
            return false;
        default:
            return false;
    }
}

}  // namespace ak::runtime