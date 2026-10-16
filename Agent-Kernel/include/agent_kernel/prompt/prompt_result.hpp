// ============================================================
// Agent Kernel - Prompt Result (Prompt boundary)
// ============================================================
// P1-IS007 Rev1.1 Chapter 14 - the completed Prompt assembly.
//
// PromptResult contains the Prompt identity, Prompt definition
// version, ordered assembled components, model-neutral
// representation metadata, and validation status (PRM-015). It
// is immutable after construction (Chapter 14.2, PRM-042) and
// model-neutral / provider-independent (PRM-016, PRM-017).
//
// Revision 1.1 introduces no PromptResult schema/version
// identifier beyond the definition version already carried by
// PromptResult (Chapter 14.1, F-08 deferred).
//
// The deterministic error model (PRM-043, Chapters 25.2, 41.4)
// classifies assembly failures through PromptAssemblyResult.
//
// NON-responsibilities:
// - A result is a value; it never mutates Context, Memory,
//   Planner, Tool, or Runtime (Chapter 14.2, AC-017).
// ============================================================

#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <agent_kernel/prompt/prompt_identity.hpp>
#include <agent_kernel/prompt/prompt_section.hpp>

namespace ak::prompt {

// Validation status carried by a successfully assembled
// PromptResult (Chapter 14.1).
enum class PromptValidationStatus : std::uint8_t {
    kValid = 0,
    kInvalid
};

// One ordered assembled component of a PromptResult
// (Chapters 11.1, 14.1). Content is the resolved, substituted
// model-neutral content.
struct AssembledComponent {
    PromptSectionKind kind = PromptSectionKind::kAdditionalContext;
    std::string content;      // resolved content (model-neutral)
    PromptMetadata metadata;  // component metadata (model-neutral)
};

// The completed, immutable Prompt assembly (Chapter 14.1).
class PromptResult final {
public:
    PromptResult(PromptId id,
                 std::string definition_version,
                 std::vector<AssembledComponent> components,
                 PromptMetadata metadata = {},
                 PromptValidationStatus validation = PromptValidationStatus::kValid);

    [[nodiscard]] const PromptId& Id() const noexcept;
    [[nodiscard]] const std::string& DefinitionVersion() const noexcept;
    [[nodiscard]] const std::vector<AssembledComponent>& Components() const noexcept;
    [[nodiscard]] const PromptMetadata& Metadata() const noexcept;
    [[nodiscard]] PromptValidationStatus ValidationStatus() const noexcept;

private:
    PromptId id_;
    std::string definition_version_;
    std::vector<AssembledComponent> components_;
    PromptMetadata metadata_;
    PromptValidationStatus validation_;
};

// Deterministic assembly status classification (Chapters 25.2,
// 41.4). No complex error taxonomy is introduced beyond this
// fixed vocabulary.
enum class PromptAssemblyStatus : std::uint8_t {
    kSuccess = 0,
    kInvalidDefinition,
    kMissingRequiredInput,
    kUnavailableRequiredMaterial,
    kUnknownBinding,
    kInvalidValue,
    kInvalidSubstitution,
    kInvalidState
};

// The deterministic assembly result envelope (Chapters 24.1,
// 41.4). On success, `result` holds the immutable PromptResult;
// on failure, `result` is nullopt and `variable` identifies the
// offending declared variable or component reference without
// exposing implementation internals (Chapter 12.3).
struct PromptAssemblyResult {
    PromptAssemblyStatus status = PromptAssemblyStatus::kInvalidState;
    std::optional<PromptResult> result = std::nullopt;
    std::string message;
    std::string variable;

    [[nodiscard]] bool Succeeded() const noexcept {
        return status == PromptAssemblyStatus::kSuccess;
    }
};

}  // namespace ak::prompt