// ============================================================
// Agent Kernel - ContextAgentContract (Context boundary)
// ============================================================
// Implementation of the Agent-facing Context coordination
// contract. The contract is Context-owned and depends on no
// Agent header: the Agent may consume it without forming a
// reverse or circular dependency.
// ============================================================

#include <agent_kernel/context/context_agent_contract.hpp>

#include <agent_kernel/context/context.hpp>

namespace ak::context {

ContextCreationService& ContextAgentContract::Creation() noexcept {
    return context_->Creation();
}

const ContextCreationService& ContextAgentContract::Creation() const noexcept {
    return context_->Creation();
}

ContextAccessService& ContextAgentContract::Access() noexcept {
    return context_->Access();
}

const ContextAccessService& ContextAgentContract::Access() const noexcept {
    return context_->Access();
}

ContextUpdateService& ContextAgentContract::Update() noexcept {
    return context_->Update();
}

const ContextUpdateService& ContextAgentContract::Update() const noexcept {
    return context_->Update();
}

ContextCompositionService& ContextAgentContract::Composition() noexcept {
    return context_->Composition();
}

const ContextCompositionService& ContextAgentContract::Composition() const noexcept {
    return context_->Composition();
}

ContextReleaseService& ContextAgentContract::Release() noexcept {
    return context_->Release();
}

const ContextReleaseService& ContextAgentContract::Release() const noexcept {
    return context_->Release();
}

}  // namespace ak::context
