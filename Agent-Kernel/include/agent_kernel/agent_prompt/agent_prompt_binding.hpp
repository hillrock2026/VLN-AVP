// ============================================================
// Agent Kernel - AgentPromptBinding (Agent-owned boundary)
// ============================================================
// P1-IS007 Rev1.1 Chapter 19.2 - the sole Agent-facing Prompt
// coordination boundary.
//
// AgentPromptBinding is a NON-OWNING view over the Prompt root
// (PRM-022): it does not own Prompt and maintains no
// independent Prompt lifecycle state (Prompt has no subsystem
// lifecycle state machine, Chapter 16.1); every operation is
// forwarded to the Prompt root and returns the Prompt root's
// own result (Chapter 19.2).
//
// AgentPromptBinding follows the established Agent-facing
// composition, ownership, lifecycle, injection, substitution,
// and non-owning reference pattern established by P1-IS005
// (AgentPlannerBinding) and P1-IS006 Rev2 (AgentToolBinding),
// insofar as applicable to Prompt (PRM-039, Chapter 19.5).
//
// NON-responsibilities:
// - No Runtime operation, no second Prompt coordination API,
//   and no lifecycle authority (PRM-048, TOL-018).
// ============================================================

#pragma once

#include <agent_kernel/prompt/prompt.hpp>

namespace ak::agent {

// The sole Agent-facing Prompt coordination boundary
// (Chapter 19.2).
class AgentPromptBinding final {
public:
    // `prompt` must outlive the binding.
    explicit AgentPromptBinding(ak::prompt::Prompt& prompt);

    AgentPromptBinding(const AgentPromptBinding&) = delete;
    AgentPromptBinding& operator=(const AgentPromptBinding&) = delete;
    AgentPromptBinding(AgentPromptBinding&&) = delete;
    AgentPromptBinding& operator=(AgentPromptBinding&&) = delete;

    ~AgentPromptBinding() = default;

    // -- identity / definition (forwarded to the Prompt root) --
    [[nodiscard]] const ak::prompt::PromptId& Id() const noexcept;
    [[nodiscard]] const ak::prompt::PromptDefinition& Definition() const noexcept;

    // -- assembly (forwarded; returns Prompt's own result) --
    [[nodiscard]] ak::prompt::PromptAssemblyResult Assemble(
        const ak::prompt::PromptAssemblyRequest& request) const;

private:
    ak::prompt::Prompt* prompt_ = nullptr;
};

}  // namespace ak::agent