// ============================================================
// Agent Kernel - Prompt Sections and Components (Prompt
// boundary)
// ============================================================
// P1-IS007 Rev1.1 Chapters 10-11 - Prompt section and
// component representation.
//
// - PromptSectionKind enumerates the eight assembly-oriented
//   material categories (PRM-046). These categories are
//   classification mechanisms for Prompt assembly only; they
//   SHALL NOT constitute architectural ownership contracts or
//   normative domain models for the source subsystems
//   (Chapter 10.1, PRM-046, AC-029).
// - PromptSection carries one kind and an ordered component
//   list; the ordering established by PromptDefinition is
//   preserved by assembly (PRM-010).
// - PromptComponent is a model-neutral unit of Prompt content
//   with a semantic kind, template content, optional variable
//   references, and optional metadata (Chapter 11.1, PRM-016).
//
// NON-responsibilities:
// - No provider-specific chat-message protocol (TOL-024).
// - No mirror domain model for any source subsystem
//   (PRM-038).
// ============================================================

#pragma once

#include <cstdint>
#include <map>
#include <string>
#include <utility>
#include <vector>

namespace ak::prompt {

// Assembly-oriented material categories (Chapter 10.1). These
// categories describe Prompt assembly semantics only; they are
// not provider-specific message kinds and not source-subsystem
// domain models.
enum class PromptSectionKind : std::uint8_t {
    kSystemInstruction = 0,
    kAgentInstruction,
    kUserInput,
    kMemoryMaterial,
    kContextMaterial,
    kPlanningMaterial,
    kToolMaterial,
    kAdditionalContext
};

// Generic model-neutral key/value metadata used by Prompt
// sections, components, definitions, requests, and results.
using PromptMetadata = std::map<std::string, std::string>;

// A model-neutral unit of Prompt content (Chapter 11.1).
class PromptComponent final {
public:
    // `content` is a template that may reference declared
    // variables through `{variable_name}` placeholders. Empty
    // or whitespace-only content is rejected as a malformed
    // component (Chapter 25.1).
    // `variable_references` declares the variable names the
    // component template expects; it is component metadata and
    // is not enforced as a separate substitution source.
    PromptComponent(PromptSectionKind kind,
                    std::string content,
                    std::vector<std::string> variable_references = {},
                    PromptMetadata metadata = {});

    [[nodiscard]] PromptSectionKind Kind() const noexcept;
    [[nodiscard]] const std::string& Content() const noexcept;
    [[nodiscard]] const std::vector<std::string>& VariableReferences() const noexcept;
    [[nodiscard]] const PromptMetadata& Metadata() const noexcept;

private:
    PromptSectionKind kind_;
    std::string content_;
    std::vector<std::string> variable_references_;
    PromptMetadata metadata_;
};

// An ordered semantic portion of a Prompt (Chapter 10.1).
class PromptSection final {
public:
    // A section must contain at least one component; an empty
    // section is invalid definition structure (Chapter 25.1).
    PromptSection(PromptSectionKind kind,
                  std::vector<PromptComponent> components,
                  PromptMetadata metadata = {});

    [[nodiscard]] PromptSectionKind Kind() const noexcept;
    [[nodiscard]] const std::vector<PromptComponent>& Components() const noexcept;
    [[nodiscard]] const PromptMetadata& Metadata() const noexcept;

private:
    PromptSectionKind kind_;
    std::vector<PromptComponent> components_;
    PromptMetadata metadata_;
};

}  // namespace ak::prompt