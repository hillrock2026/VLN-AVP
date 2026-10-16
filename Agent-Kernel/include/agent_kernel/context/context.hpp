// ============================================================
// Agent Kernel - Context (Context boundary)
// ============================================================
// The Context root representation (P1-IS004 Chapter 7.1).
//
// The Context root owns:
//   - Context identity;
//   - Context configuration;
//   - execution context and intelligent working state
//     (through Context Objects);
//   - per-Object Context lifecycle;
//   - per-Object Context operational state;
//   - Context Services (Creation / Access / Update /
//     Composition / Release);
//   - contextual relationships;
//   - Context extensions;
//   - the Agent-facing coordination contract.
//
// NON-responsibilities:
// - Context does not own Agent, Memory, Planner, Tool, or
//   Runtime objects.
// - Context does not own persistent knowledge (Memory owns
//   knowledge retention).
// - Context does not coordinate peers and performs no Runtime
//   action (Phase 2: no Runtime integration).
// ============================================================

#pragma once

#include <utility>

#include <agent_kernel/context/context_agent_contract.hpp>
#include <agent_kernel/context/context_extensions.hpp>
#include <agent_kernel/context/context_identity.hpp>
#include <agent_kernel/context/context_services.hpp>
#include <agent_kernel/context/context_store.hpp>
#include <agent_kernel/foundation/kernel_diagnostics.hpp>
#include <agent_kernel/foundation/kernel_metadata.hpp>

namespace ak::context {

class Context {
public:
    explicit Context(ContextIdentity identity);

    // -- Identity --
    [[nodiscard]] ContextIdentity GetIdentity() const noexcept { return identity_; }

    // -- Configuration (Context-owned) --
    void SetConfiguration(ak::KernelMetadata configuration) {
        configuration_ = std::move(configuration);
    }
    [[nodiscard]] const ak::KernelMetadata& GetConfiguration() const noexcept {
        return configuration_;
    }

    // -- Context Services (sole service boundary) --
    [[nodiscard]] ContextCreationService& Creation() noexcept { return creation_; }
    [[nodiscard]] const ContextCreationService& Creation() const noexcept {
        return creation_;
    }
    [[nodiscard]] ContextAccessService& Access() noexcept { return access_; }
    [[nodiscard]] const ContextAccessService& Access() const noexcept {
        return access_;
    }
    [[nodiscard]] ContextUpdateService& Update() noexcept { return update_; }
    [[nodiscard]] const ContextUpdateService& Update() const noexcept {
        return update_;
    }
    [[nodiscard]] ContextCompositionService& Composition() noexcept {
        return composition_;
    }
    [[nodiscard]] const ContextCompositionService& Composition() const noexcept {
        return composition_;
    }
    [[nodiscard]] ContextReleaseService& Release() noexcept { return release_; }
    [[nodiscard]] const ContextReleaseService& Release() const noexcept {
        return release_;
    }

    // -- Boundaries --
    [[nodiscard]] ContextAgentContract& AgentContract() noexcept {
        return agent_contract_;
    }
    [[nodiscard]] const ContextAgentContract& AgentContract() const noexcept {
        return agent_contract_;
    }

    [[nodiscard]] ContextExtensionBoundary& Extensions() noexcept {
        return extensions_;
    }
    [[nodiscard]] const ContextExtensionBoundary& Extensions() const noexcept {
        return extensions_;
    }

    // -- Diagnostics (owner-scoped) --
    [[nodiscard]] ak::DiagnosticSink& Diagnostics() noexcept { return diagnostics_; }
    [[nodiscard]] const ak::DiagnosticSink& Diagnostics() const noexcept {
        return diagnostics_;
    }

private:
    ContextIdentity identity_;
    ak::KernelMetadata configuration_;
    ContextStore store_;
    ContextCreationService creation_;
    ContextAccessService access_;
    ContextUpdateService update_;
    ContextCompositionService composition_;
    ContextReleaseService release_;
    ContextAgentContract agent_contract_;
    ContextExtensionBoundary extensions_;
    ak::DiagnosticSink diagnostics_;
};

}  // namespace ak::context

