// ============================================================
// Agent Kernel - Tool Extension Model (Tool boundary)
// ============================================================
// P1-IS006 Rev2 Chapter 26 - Tool extension interfaces.
//
// Extensions receive a Tool-owned context view (TOL-085); an
// extension SHALL NOT acquire the Tool root or the
// AgentToolBinding through the extension contract.
//
// The Tool root SHALL own extension attach, detach, and
// destruction (TOL-103); the Agent SHALL NOT invoke Attach or
// Detach.
//
// Extension invariants (TOL-062): an extension SHALL NOT become
// a second Tool, a Planner, an Agent coordinator, or Runtime;
// it SHALL NOT modify Runtime lifecycle, schedule Runtime
// execution, resolve Runtime capabilities, or bypass Agent
// coordination.
//
// NON-responsibilities:
// - IToolExtensionContext exposes no lifecycle mutation,
//   Agent-facing coordination, or Runtime operations.
// ============================================================

#pragma once

#include <memory>
#include <string>

#include <agent_kernel/tool/tool_identity.hpp>
#include <agent_kernel/tool/tool_result.hpp>
#include <agent_kernel/tool/tool_services.hpp>
#include <agent_kernel/tool/tool_state.hpp>

namespace ak::tool {

// Tool-owned extension context view (Chapter 26.1).
class IToolExtensionContext {
public:
    virtual ~IToolExtensionContext() = default;

    [[nodiscard]] virtual const ToolId& Id() const noexcept = 0;

    [[nodiscard]] virtual ToolLifecycleState LifecycleState() const noexcept = 0;

    [[nodiscard]] virtual ToolOperationalState OperationalState() const noexcept = 0;

    [[nodiscard]] virtual IToolCapabilityService& Capabilities() noexcept = 0;

    [[nodiscard]] virtual IToolProviderService& Providers() noexcept = 0;
};

// Tool extension interface (Chapter 26.2).
class IToolExtension {
public:
    virtual ~IToolExtension() = default;

    [[nodiscard]] virtual std::string Name() const = 0;

    virtual void Attach(IToolExtensionContext& context) = 0;

    virtual void Detach(IToolExtensionContext& context) = 0;
};

// Tool extension service (Chapter 26.3).
class IToolExtensionService {
public:
    virtual ~IToolExtensionService() = default;

    [[nodiscard]] virtual ExtensionResult RegisterExtension(
        std::unique_ptr<IToolExtension> extension) = 0;

    [[nodiscard]] virtual ExtensionResult UnregisterExtension(
        const std::string& name) = 0;

    [[nodiscard]] virtual bool IsAttached(const std::string& name) const noexcept = 0;
};

}  // namespace ak::tool