#include <agent_kernel/state.hpp>
#include <stdexcept>

namespace ak {

bool IsValidTransition(KernelObjectState from, KernelObjectState to) noexcept {
    // kCreated -> kInitialized
    if (from == KernelObjectState::kCreated && to == KernelObjectState::kInitialized) return true;
    // kInitialized -> kReady
    if (from == KernelObjectState::kInitialized && to == KernelObjectState::kReady) return true;
    // kReady -> kRunning, kCompleted, kFailed, kDestroyed
    if (from == KernelObjectState::kReady && to == KernelObjectState::kRunning) return true;
    if (from == KernelObjectState::kReady && to == KernelObjectState::kCompleted) return true;
    if (from == KernelObjectState::kReady && to == KernelObjectState::kFailed) return true;
    if (from == KernelObjectState::kReady && to == KernelObjectState::kDestroyed) return true;
    // kRunning -> kCompleted, kFailed, kSuspended
    if (from == KernelObjectState::kRunning && to == KernelObjectState::kCompleted) return true;
    if (from == KernelObjectState::kRunning && to == KernelObjectState::kFailed) return true;
    if (from == KernelObjectState::kRunning && to == KernelObjectState::kSuspended) return true;
    // kSuspended -> kReady
    if (from == KernelObjectState::kSuspended && to == KernelObjectState::kReady) return true;
    // kCompleted -> kDestroyed
    if (from == KernelObjectState::kCompleted && to == KernelObjectState::kDestroyed) return true;
    // kFailed -> kDestroyed
    if (from == KernelObjectState::kFailed && to == KernelObjectState::kDestroyed) return true;
    return false;
}

bool IsTerminal(KernelObjectState state) noexcept {
    return state == KernelObjectState::kCompleted ||
           state == KernelObjectState::kFailed ||
           state == KernelObjectState::kDestroyed;
}

}  // namespace ak
