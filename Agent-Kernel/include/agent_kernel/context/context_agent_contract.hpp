// ============================================================
// Agent Kernel - ContextAgentContract (Context boundary)
// ============================================================
// Agent-facing Context coordination contract.
//
// P1-IS004 scope (Chapter 14 - Agent-Context Interaction,
// Chapter 27):
// - The Agent is the sole architectural coordinator of Context.
// - This contract is the Agent-facing surface: the Agent
//   requests Context creation, inspection, update, composition,
//   and release through Context Services.
// - The contract is expressed inside the Context boundary so
//   that Context never depends on Agent headers (no reverse
//   target dependency and no circular link).
//
// NON-responsibilities:
// - This contract grants Context no cross-subsystem
//   coordination authority and no Agent access.
// - It references no Runtime type and performs no Runtime
//   action.
// ============================================================

#pragma once

#include <cstdint>
#include <string_view>

#include <agent_kernel/context/context_services.hpp>

namespace ak::context {

class Context;

class ContextAgentContract {
public:
    explicit ContextAgentContract(Context& context) noexcept : context_(&context) {}

    // Architectural contract name (AK0043 "Context").
    [[nodiscard]] std::string_view ContractName() const noexcept {
        return "Context";
    }

    // Agent-facing Context service surface (the sole service
    // boundary). Context retains ownership of every service.
    [[nodiscard]] ContextCreationService& Creation() noexcept;
    [[nodiscard]] const ContextCreationService& Creation() const noexcept;
    [[nodiscard]] ContextAccessService& Access() noexcept;
    [[nodiscard]] const ContextAccessService& Access() const noexcept;
    [[nodiscard]] ContextUpdateService& Update() noexcept;
    [[nodiscard]] const ContextUpdateService& Update() const noexcept;
    [[nodiscard]] ContextCompositionService& Composition() noexcept;
    [[nodiscard]] const ContextCompositionService& Composition() const noexcept;
    [[nodiscard]] ContextReleaseService& Release() noexcept;
    [[nodiscard]] const ContextReleaseService& Release() const noexcept;

private:
    Context* context_ = nullptr;
};

}  // namespace ak::context
