// ============================================================
// Agent Kernel - AgentPromptBinding implementation
// (Agent-owned boundary)
// ============================================================
// P1-IS007 Rev1.1 Chapter 19.2. The binding is a NON-OWNING
// view over the Prompt root (PRM-022). It maintains no
// independent lifecycle state (Prompt has no subsystem
// lifecycle state machine, Chapter 16.1); every operation is
// forwarded to the Prompt root and returns the Prompt root's
// own result (Chapter 19.2).
//
// NON-responsibilities:
// - No Runtime operation; no second Prompt coordination API;
//   no lifecycle authority (PRM-048).
// ============================================================

#include <agent_kernel/agent_prompt/agent_prompt_binding.hpp>

namespace ak::agent {

AgentPromptBinding::AgentPromptBinding(ak::prompt::Prompt& prompt)
    : prompt_(&prompt) {}

const ak::prompt::PromptId& AgentPromptBinding::Id() const noexcept {
    return prompt_->Id();
}

const ak::prompt::PromptDefinition& AgentPromptBinding::Definition() const noexcept {
    return prompt_->Definition();
}

ak::prompt::PromptAssemblyResult AgentPromptBinding::Assemble(
    const ak::prompt::PromptAssemblyRequest& request) const {
    return prompt_->Assembly().Assemble(request);
}

}  // namespace ak::agent