// ============================================================
// Agent Kernel - AgentPromptHost implementation (Agent-owned
// composition root)
// ============================================================
// P1-IS007 Rev1.1 Chapter 19.3. Member order is normative:
// prompt_, binding_ (declaration order = init order);
// destruction occurs in reverse order: binding_, prompt_
// (Chapter 19.5 pattern).
//
// AgentPromptHost owns the Prompt root (PRM-023); the binding
// is a non-owning view over Prompt. Constructing the Prompt
// root is ordinary object construction and is NOT Prompt
// subsystem lifecycle authority (PRM-048, Chapters 16.1, 19.3).
//
// NON-responsibilities:
// - No Runtime action; the host exposes no public Prompt()
//   accessor.
// ============================================================

#include <agent_kernel/agent_prompt/agent_prompt_host.hpp>

#include <utility>

namespace ak::agent {

AgentPromptHost::AgentPromptHost(ak::prompt::PromptDefinition definition)
    : prompt_(std::move(definition)), binding_(prompt_) {}

AgentPromptBinding& AgentPromptHost::Binding() noexcept {
    return binding_;
}

const AgentPromptBinding& AgentPromptHost::Binding() const noexcept {
    return binding_;
}

}  // namespace ak::agent