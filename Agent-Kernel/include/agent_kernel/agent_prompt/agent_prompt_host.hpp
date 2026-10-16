// ============================================================
// Agent Kernel - AgentPromptHost (Agent-owned composition root)
// ============================================================
// P1-IS007 Rev1.1 Chapter 19.3 - the single production
// composition root for Prompt integration.
//
// Construction order is normative (Chapter 19.5, following the
// P1-IS005 Chapter 16 / P1-IS006 Rev2 §25 pattern):
//   AgentPromptHost -> Prompt -> AgentPromptBinding
// Member order: prompt_, binding_ (declaration order = init
// order); destruction occurs in reverse order: binding_,
// prompt_.
//
// AgentPromptHost owns the Prompt root (PRM-023); the binding
// is a non-owning view over Prompt. The host SHALL NOT expose
// a public Prompt() accessor: the Agent coordinates Prompt
// exclusively through AgentPromptHost::Binding().
//
// AgentPromptHost SHALL NOT become a second Agent lifecycle
// authority (PRM-048, TOL-033): constructing the Prompt root
// as an ordinary owned object is ordinary object construction,
// not Prompt subsystem lifecycle authority (Chapters 16.1,
// 19.3). Prompt has no subsystem lifecycle state machine.
//
// NON-responsibilities:
// - The host performs no Runtime action and is not a second
//   composition root.
// ============================================================

#pragma once

#include <agent_kernel/agent_prompt/agent_prompt_binding.hpp>
#include <agent_kernel/prompt/prompt.hpp>

namespace ak::agent {

// The single production composition root (Chapter 19.3).
class AgentPromptHost final {
public:
    explicit AgentPromptHost(ak::prompt::PromptDefinition definition);

    AgentPromptHost(const AgentPromptHost&) = delete;
    AgentPromptHost& operator=(const AgentPromptHost&) = delete;
    AgentPromptHost(AgentPromptHost&&) = delete;
    AgentPromptHost& operator=(AgentPromptHost&&) = delete;

    ~AgentPromptHost() = default;

    // -- Agent-owned production surface --
    [[nodiscard]] const AgentPromptBinding& Binding() const noexcept;
    [[nodiscard]] AgentPromptBinding& Binding() noexcept;

private:
    // member order is normative (declaration order = init order)
    ak::prompt::Prompt prompt_;
    AgentPromptBinding binding_;
};

}  // namespace ak::agent