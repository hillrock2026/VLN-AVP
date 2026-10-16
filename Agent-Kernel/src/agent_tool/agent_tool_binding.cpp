// ============================================================
// Agent Kernel - AgentToolBinding implementation (Agent-owned
// boundary)
// ============================================================
// P1-IS006 Rev2 Chapter 24. The binding is a NON-OWNING view
// over the Tool root (TOL-054). It maintains no independent
// lifecycle state (TOL-055); every operation is forwarded to
// the Tool root and returns the Tool root's own result
// (TOL-056).
//
// NON-responsibilities:
// - No Runtime operation; no second Tool API; no lifecycle
//   authority.
// ============================================================

#include <agent_kernel/agent_tool/agent_tool_binding.hpp>

namespace ak::agent {

AgentToolBinding::AgentToolBinding(ak::tool::Tool& tool) : tool_(&tool) {}

const ak::tool::ToolId& AgentToolBinding::Id() const noexcept {
    return tool_->Id();
}

ak::tool::ToolLifecycleState AgentToolBinding::LifecycleState() const noexcept {
    return tool_->LifecycleState();
}

ak::tool::ToolOperationalState AgentToolBinding::OperationalState() const noexcept {
    return tool_->OperationalState();
}

ak::tool::ToolLifecycleResult AgentToolBinding::Register() {
    return tool_->Register();
}

ak::tool::ToolLifecycleResult AgentToolBinding::Activate() {
    return tool_->Activate();
}

ak::tool::ToolLifecycleResult AgentToolBinding::Suspend() {
    return tool_->Suspend();
}

ak::tool::ToolLifecycleResult AgentToolBinding::Resume() {
    return tool_->Resume();
}

ak::tool::ToolLifecycleResult AgentToolBinding::Retire() {
    return tool_->Retire();
}

ak::tool::ToolLifecycleResult AgentToolBinding::FinalizeRetirement() {
    return tool_->FinalizeRetirement();
}

ak::tool::ToolCapabilityResult AgentToolBinding::GetCapability(
    const ak::tool::CapabilityId& capability_id) const {
    return tool_->Capabilities().Get(capability_id);
}

ak::tool::ToolDiscoveryResult AgentToolBinding::Discover() const {
    return tool_->Discovery().ListCapabilities();
}

ak::tool::InvocationPreparationResult AgentToolBinding::PrepareInvocation(
    const ak::tool::InvocationRequest& request) const {
    return tool_->InvocationPreparation().PrepareInvocation(request);
}

}  // namespace ak::agent