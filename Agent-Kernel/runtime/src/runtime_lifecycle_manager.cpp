#include <runtime_lifecycle_manager.h>

namespace ak::runtime {

RuntimeLifecycleManager::RuntimeLifecycleManager(RuntimeStateMachine& stateMachine) noexcept
    : stateMachine_(stateMachine), hasFailed_(false) {}

bool RuntimeLifecycleManager::Initialize() noexcept {
    if (!stateMachine_.CanTransitionTo(RuntimeState::kRunning)) return false;
    return stateMachine_.TransitionTo(RuntimeState::kRunning);
}

void RuntimeLifecycleManager::Shutdown() noexcept {
    if (stateMachine_.GetState() == RuntimeState::kRunning) {
        (void)stateMachine_.TransitionTo(RuntimeState::kStopped);
    }
}

void RuntimeLifecycleManager::Fail(const std::string& reason) noexcept {
    if (stateMachine_.IsTerminal()) return;
    failureReason_ = reason;
    hasFailed_ = true;
    (void)stateMachine_.TransitionTo(RuntimeState::kFailed);
}

const std::string& RuntimeLifecycleManager::GetFailureReason() const noexcept {
    return failureReason_;
}

bool RuntimeLifecycleManager::HasFailed() const noexcept {
    return hasFailed_;
}

}  // namespace ak::runtime