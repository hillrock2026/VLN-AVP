// ============================================================
// Agent Kernel - AgentToolBinding (Agent-owned boundary)
// ============================================================
// P1-IS006 Rev2 Chapter 24 - the sole Agent-facing Tool
// coordination boundary.
//
// AgentToolBinding is a NON-OWNING view over the Tool root
// (TOL-054): it does not own Tool and maintains no independent
// Tool lifecycle state (TOL-055); every operation is forwarded
// to the Tool root and returns the Tool root's own result.
//
// TOL-086: ak::agent::IToolContract (P1-IS002) and
// AgentCoordinationService::BindTool remain exactly as
// approved in P1-IS002; the real Phase 4 Tool capability path
// is AgentToolBinding -> Tool (TOL-056).
//
// NON-responsibilities:
// - No Runtime operation, no second Tool API, no lifecycle
//   authority.
// ============================================================

#pragma once

#include <agent_kernel/tool/tool.hpp>

namespace ak::agent {

// The sole Agent-facing Tool coordination boundary (TOL-056).
class AgentToolBinding final {
public:
    explicit AgentToolBinding(ak::tool::Tool& tool);

    AgentToolBinding(const AgentToolBinding&) = delete;
    AgentToolBinding& operator=(const AgentToolBinding&) = delete;
    AgentToolBinding(AgentToolBinding&&) = delete;
    AgentToolBinding& operator=(AgentToolBinding&&) = delete;

    ~AgentToolBinding() = default;

    // -- identity / state (forwarded to the Tool root) --
    [[nodiscard]] const ak::tool::ToolId& Id() const noexcept;
    [[nodiscard]] ak::tool::ToolLifecycleState LifecycleState() const noexcept;
    [[nodiscard]] ak::tool::ToolOperationalState OperationalState() const noexcept;

    // -- lifecycle (forwarded) --
    [[nodiscard]] ak::tool::ToolLifecycleResult Register();
    [[nodiscard]] ak::tool::ToolLifecycleResult Activate();
    [[nodiscard]] ak::tool::ToolLifecycleResult Suspend();
    [[nodiscard]] ak::tool::ToolLifecycleResult Resume();
    [[nodiscard]] ak::tool::ToolLifecycleResult Retire();
    [[nodiscard]] ak::tool::ToolLifecycleResult FinalizeRetirement();

    // -- capability / discovery / invocation preparation --
    [[nodiscard]] ak::tool::ToolCapabilityResult GetCapability(
        const ak::tool::CapabilityId& capability_id) const;
    [[nodiscard]] ak::tool::ToolDiscoveryResult Discover() const;
    [[nodiscard]] ak::tool::InvocationPreparationResult PrepareInvocation(
        const ak::tool::InvocationRequest& request) const;

private:
    ak::tool::Tool* tool_ = nullptr;
};

}  // namespace ak::agent