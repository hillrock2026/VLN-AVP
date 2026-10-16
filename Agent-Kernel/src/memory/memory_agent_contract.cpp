// ============================================================
// Agent Kernel - MemoryAgentContract (Memory boundary)
// ============================================================
// Implementation of the Agent-facing Memory coordination
// contract. The contract is Memory-owned and depends on no
// Agent header: the Agent may consume it without forming a
// reverse or circular dependency.
// ============================================================

#include <agent_kernel/memory/memory_agent_contract.hpp>

#include <agent_kernel/memory/memory.hpp>

namespace ak::memory {

MemoryResult MemoryAgentContract::RequestLifecycleParticipation(
    MemoryLifecycleParticipation request) {
    // Memory owns and validates every transition; the Agent only
    // requests participation.
    switch (request) {
        case MemoryLifecycleParticipation::kInitialize:
            return memory_->InitializeLifecycle();
        case MemoryLifecycleParticipation::kActivate:
            return memory_->CompleteInitialization();
        case MemoryLifecycleParticipation::kSuspend:
            return memory_->Suspend();
        case MemoryLifecycleParticipation::kResume:
            return memory_->Resume();
        case MemoryLifecycleParticipation::kTerminate:
            return memory_->Terminate();
        case MemoryLifecycleParticipation::kDispose:
            return memory_->Dispose();
    }
    return {MemoryResultStatus::kRejected, "unknown lifecycle participation request"};
}

MemoryLifecycleState MemoryAgentContract::InspectLifecycleState() const noexcept {
    return memory_->GetLifecycleState();
}

MemoryOperationalState MemoryAgentContract::InspectOperationalState() const noexcept {
    return memory_->GetOperationalState();
}

MemoryService& MemoryAgentContract::Services() noexcept {
    return memory_->Services();
}

const MemoryService& MemoryAgentContract::Services() const noexcept {
    return memory_->Services();
}

}  // namespace ak::memory