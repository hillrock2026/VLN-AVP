// ============================================================
// Agent Kernel - Memory (Memory boundary)
// ============================================================
// Implementation of the Memory root representation. Memory owns
// its lifecycle, operational state, store, services, provider,
// extensions, and the Agent-facing coordination contract.
// ============================================================

#include <agent_kernel/memory/memory.hpp>

#include <memory>
#include <utility>

namespace ak::memory {

Memory::Memory(MemoryIdentity identity)
    : Memory(identity, std::make_shared<InProcessMemoryProvider>()) {}

Memory::Memory(MemoryIdentity identity, std::shared_ptr<IMemoryProvider> provider)
    : identity_(identity),
      provider_(std::move(provider)),
      services_(lifecycle_, operational_, store_, provider_.get()),
      agent_contract_(*this) {}

MemoryResult Memory::InitializeLifecycle() {
    return lifecycle_.Initialize();
}

MemoryResult Memory::CompleteInitialization() {
    return lifecycle_.Activate();
}

MemoryResult Memory::Suspend() {
    return lifecycle_.Suspend();
}

MemoryResult Memory::Resume() {
    return lifecycle_.Resume();
}

MemoryResult Memory::Terminate() {
    return lifecycle_.Terminate();
}

MemoryResult Memory::Dispose() {
    return lifecycle_.Dispose();
}

MemoryResult Memory::MarkReady() {
    return operational_.ToReady();
}

MemoryResult Memory::MarkAvailable() {
    return operational_.ToAvailable();
}

MemoryResult Memory::MarkBusy() {
    return operational_.ToBusy();
}

MemoryResult Memory::MarkDegraded() {
    return operational_.ToDegraded();
}

MemoryResult Memory::MarkUnavailable() {
    return operational_.ToUnavailable();
}

std::shared_ptr<IMemoryProvider> Memory::SetProvider(
    std::shared_ptr<IMemoryProvider> provider) noexcept {
    if (provider == nullptr) {
        // Null is rejected: the current provider is retained.
        return provider_;
    }
    std::shared_ptr<IMemoryProvider> previous = std::move(provider_);
    provider_ = std::move(provider);
    services_.BindProvider(*provider_);
    return previous;
}

}  // namespace ak::memory