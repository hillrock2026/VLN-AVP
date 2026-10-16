// ============================================================
// Agent Kernel - Prompt Definition (Prompt boundary)
// ============================================================
// P1-IS007 Rev1.1 Chapter 9 - immutable Prompt assembly
// configuration.
//
// A PromptDefinition contains the PromptId, version, ordered
// sections, section metadata, declared variables, validation
// rules, and assembly ordering information (PRM-009). It is
// immutable after construction (Chapters 9.1, 17).
//
// Construction rejects: an empty version, an empty ordered
// section list (no assembly ordering can be established),
// duplicate variable names, and malformed sections or
// components (Chapter 25.1).
//
// NON-responsibilities:
// - The definition performs no retrieval and selects no
//   PromptDefinition; selection remains the responsibility of
//   the Agent or the appropriate future coordination / policy
//   layer (PRM-045, Chapter 41.6).
// ============================================================

#pragma once

#include <string>
#include <utility>
#include <vector>

#include <agent_kernel/prompt/prompt_identity.hpp>
#include <agent_kernel/prompt/prompt_section.hpp>
#include <agent_kernel/prompt/prompt_variable.hpp>

namespace ak::prompt {

// Immutable Prompt assembly configuration (Chapter 9.1).
class PromptDefinition final {
public:
    PromptDefinition(PromptId id,
                     std::string version,
                     std::vector<PromptSection> sections,
                     std::vector<PromptVariable> variables,
                     PromptMetadata metadata = {});

    [[nodiscard]] const PromptId& Id() const noexcept;
    [[nodiscard]] const std::string& Version() const noexcept;
    [[nodiscard]] const std::vector<PromptSection>& Sections() const noexcept;
    [[nodiscard]] const std::vector<PromptVariable>& Variables() const noexcept;
    [[nodiscard]] const PromptMetadata& Metadata() const noexcept;

private:
    PromptId id_;
    std::string version_;
    std::vector<PromptSection> sections_;
    std::vector<PromptVariable> variables_;
    PromptMetadata metadata_;
};

}  // namespace ak::prompt