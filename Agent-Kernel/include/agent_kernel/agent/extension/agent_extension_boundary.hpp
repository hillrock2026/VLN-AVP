// ============================================================
// Agent Kernel - AgentExtensionBoundary (Agent boundary)
// ============================================================
// Agent-specific extension boundary.
//
// P1-IS002 scope (Chapter 18 - Agent-specific Extension Model):
// - The Agent owns the Agent-specific extension boundary,
//   Agent-specific extensions, and their lifecycle, state,
//   configuration, integrity, compatibility, and governance.
// - Agent-specific extensions MAY provide intelligent
//   reasoning, policy behavior, learning components,
//   perception, and future Agent-specific capabilities. They
//   SHALL NOT provide planning: planning remains Planner-owned.
//
// NON-responsibilities (P1-IS002 Chapter 18.2):
// - Planner, Memory, Context, and Tool extensions attach only
//   to their own subsystem extension boundaries and SHALL NOT
//   attach through this boundary.
// - The Agent SHALL NOT directly coordinate subsystem
//   internal extensions.
// - This boundary is an implementation boundary/mechanism, NOT
//   a new Kernel architectural subsystem named "Extension".
// ============================================================

#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

#include <agent_kernel/foundation/kernel_diagnostics.hpp>
#include <agent_kernel/foundation/kernel_metadata.hpp>

namespace ak::agent {

// Architectural domain of an extension. Only the Agent-specific
// domain may attach to the Agent-specific extension boundary.
enum class AgentExtensionDomain : std::uint8_t {
    kAgentSpecific = 0,
    kPlanner,
    kMemory,
    kContext,
    kTool,
    kUnknown
};

struct AgentExtensionVersion {
    std::uint32_t major = 0;
    std::uint32_t minor = 0;
};

struct AttachResult {
    bool accepted = false;
    const char* message = "";
};

// Interface implemented by Agent-specific extensions. Extensions
// owned by Planner, Memory, Context, or Tool SHALL NOT implement
// this interface.
class IAgentExtension {
public:
    virtual ~IAgentExtension() noexcept = default;

    [[nodiscard]] virtual std::string_view Name() const noexcept = 0;
    [[nodiscard]] virtual AgentExtensionDomain Domain() const noexcept = 0;
    [[nodiscard]] virtual AgentExtensionVersion Version() const noexcept = 0;

    // Integrity self-check invoked by Agent-owned boundary
    // validation.
    [[nodiscard]] virtual bool SelfCheck() const noexcept = 0;
};

// Extension lifecycle/state managed by the boundary on behalf of
// the Agent. This is an internal representation detail, not an
// architectural state of the Agent.
enum class AgentExtensionState : std::uint8_t {
    kDetached = 0,
    kAttached,
    kActive,
    kSuspended
};

// Agent-owned boundary that hosts Agent-specific extensions only.
class AgentExtensionBoundary {
public:
    AgentExtensionBoundary() = default;

    // Attaches an Agent-specific extension. Subsystem extensions
    // (Planner/Memory/Context/Tool domains) are rejected.
    AttachResult Attach(std::shared_ptr<IAgentExtension> extension);

    bool Detach(std::string_view name);

    // -- Agent-owned extension lifecycle --
    bool Activate(std::string_view name);
    bool Suspend(std::string_view name);

    // -- Agent-owned extension configuration --
    bool SetConfiguration(std::string_view name, ak::KernelMetadata configuration);

    // -- Query --
    [[nodiscard]] std::size_t Count() const noexcept { return entries_.size(); }

    [[nodiscard]] bool Contains(std::string_view name) const noexcept;

    [[nodiscard]] std::vector<std::string> Enumerate() const;

    [[nodiscard]] AgentExtensionState GetState(std::string_view name) const noexcept;

    // -- Integrity and compatibility (Agent-owned governance) --
    [[nodiscard]] bool ValidateIntegrity() const noexcept;
    [[nodiscard]] bool ValidateCompatibility() const noexcept;

    // Boundary validation: reports errors for any non-Agent-
    // specific extension (should never occur: Attach rejects),
    // integrity failures, and compatibility failures.
    void ValidateBoundary(ak::DiagnosticSink& sink) const;

    // True when a subsystem extension is attached. A conforming
    // boundary is always false here.
    [[nodiscard]] bool ContainsSubsystemExtension() const noexcept;

    // Major version supported by the boundary for compatibility
    // validation.
    [[nodiscard]] static constexpr std::uint32_t SupportedMajorVersion() noexcept {
        return 1;
    }

private:
    struct Entry {
        std::shared_ptr<IAgentExtension> extension;
        AgentExtensionState state = AgentExtensionState::kAttached;
        ak::KernelMetadata configuration;
    };

    [[nodiscard]] Entry* Find(std::string_view name) noexcept;
    [[nodiscard]] const Entry* Find(std::string_view name) const noexcept;

    std::vector<Entry> entries_;
};

}  // namespace ak::agent
