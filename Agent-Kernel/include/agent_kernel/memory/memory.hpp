// ============================================================
// Agent Kernel - Memory (Memory boundary)
// ============================================================
// The Memory root representation (P1-IS003 Chapter 7.2).
//
// The Memory root owns:
//   - Memory identity;
//   - Memory configuration;
//   - Memory lifecycle;
//   - Memory operational state;
//   - Memory Domains, Objects, Entries, Metadata, References
//     (through the Memory-owned store);
//   - Memory Services;
//   - Memory Providers;
//   - Memory extensions;
//   - the Agent-facing coordination contract.
//
// NON-responsibilities:
// - Memory does not own Agent, Context, Planner, Tool, or
//   Runtime objects.
// - Memory does not coordinate peers and performs no Runtime
//   action (Phase 2: no Runtime integration).
// ============================================================

#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>

#include <agent_kernel/foundation/kernel_diagnostics.hpp>
#include <agent_kernel/foundation/kernel_metadata.hpp>
#include <agent_kernel/memory/memory_agent_contract.hpp>
#include <agent_kernel/memory/memory_extensions.hpp>
#include <agent_kernel/memory/memory_identity.hpp>
#include <agent_kernel/memory/memory_lifecycle.hpp>
#include <agent_kernel/memory/memory_operational_state.hpp>
#include <agent_kernel/memory/memory_provider.hpp>
#include <agent_kernel/memory/memory_services.hpp>
#include <agent_kernel/memory/memory_store.hpp>

namespace ak::memory {

class Memory {
public:
    explicit Memory(MemoryIdentity identity);
    Memory(MemoryIdentity identity, std::shared_ptr<IMemoryProvider> provider);

    // -- Identity --
    [[nodiscard]] MemoryIdentity GetIdentity() const noexcept { return identity_; }

    // -- Configuration (Memory-owned) --
    void SetConfiguration(ak::KernelMetadata configuration) {
        configuration_ = std::move(configuration);
    }
    [[nodiscard]] const ak::KernelMetadata& GetConfiguration() const noexcept {
        return configuration_;
    }

    // -- Lifecycle (Memory-owned transitions) --
    [[nodiscard]] MemoryResult InitializeLifecycle();    // Registered -> Initializing
    [[nodiscard]] MemoryResult CompleteInitialization(); // Initializing -> Active
    [[nodiscard]] MemoryResult Suspend();                // Active -> Suspended
    [[nodiscard]] MemoryResult Resume();                 // Suspended -> Active
    [[nodiscard]] MemoryResult Terminate();              // Active/Suspended -> Terminating
    [[nodiscard]] MemoryResult Dispose();                // Terminating -> Disposed

    [[nodiscard]] MemoryLifecycleState GetLifecycleState() const noexcept {
        return lifecycle_.GetState();
    }

    [[nodiscard]] std::string_view GetLifecycleStateName() const noexcept {
        return lifecycle_.GetStateName();
    }

    // -- Operational state (Memory-owned management) --
    [[nodiscard]] MemoryResult MarkReady();      // Unavailable -> Ready
    [[nodiscard]] MemoryResult MarkAvailable();  // Ready -> Available
    [[nodiscard]] MemoryResult MarkBusy();       // Available -> Busy
    [[nodiscard]] MemoryResult MarkDegraded();   // Available/Busy -> Degraded
    [[nodiscard]] MemoryResult MarkUnavailable();// Available/Degraded -> Unavailable

    [[nodiscard]] MemoryOperationalState GetOperationalState() const noexcept {
        return operational_.GetState();
    }

    [[nodiscard]] std::string_view GetOperationalStateName() const noexcept {
        return operational_.GetStateName();
    }

    // -- Provider (Memory-owned) --
    // Replaces the provider and returns the previous one.
    // A null provider is rejected (the current provider is
    // retained).
    [[nodiscard]] std::shared_ptr<IMemoryProvider> SetProvider(
        std::shared_ptr<IMemoryProvider> provider) noexcept;
    [[nodiscard]] bool HasProvider() const noexcept { return provider_ != nullptr; }

    // -- Boundaries --
    [[nodiscard]] MemoryService& Services() noexcept { return services_; }
    [[nodiscard]] const MemoryService& Services() const noexcept { return services_; }

    [[nodiscard]] MemoryAgentContract& AgentContract() noexcept {
        return agent_contract_;
    }
    [[nodiscard]] const MemoryAgentContract& AgentContract() const noexcept {
        return agent_contract_;
    }

    [[nodiscard]] MemoryExtensionBoundary& Extensions() noexcept { return extensions_; }
    [[nodiscard]] const MemoryExtensionBoundary& Extensions() const noexcept {
        return extensions_;
    }

    // -- Diagnostics (owner-scoped) --
    [[nodiscard]] ak::DiagnosticSink& Diagnostics() noexcept { return diagnostics_; }
    [[nodiscard]] const ak::DiagnosticSink& Diagnostics() const noexcept {
        return diagnostics_;
    }

private:
    MemoryIdentity identity_;
    ak::KernelMetadata configuration_;
    MemoryLifecycle lifecycle_;
    MemoryOperationalStateMachine operational_;
    MemoryStore store_;
    std::shared_ptr<IMemoryProvider> provider_;
    MemoryService services_;
    MemoryAgentContract agent_contract_;
    MemoryExtensionBoundary extensions_;
    ak::DiagnosticSink diagnostics_;
};

}  // namespace ak::memory