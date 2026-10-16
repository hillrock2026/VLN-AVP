// ============================================================
// Agent Kernel - Model Input (Model boundary)
// ============================================================
// P1-IS008 Rev1.0 Chapters 7, 12 - Model input representation.
//
// ModelInput is the immutable model-facing representation that
// Prompt-assembled information is translated into. The Model
// SHALL NOT assemble its own input from Context, Memory,
// Planner, Tool, or Runtime (Chapters 7, 12); it consumes only
// the model-facing input handed to it by Agent coordination.
//
// Construction rejects empty or whitespace-only content with
// std::invalid_argument (InvalidInput category, Chapter 14).
// This follows the deterministic construction-failure
// convention established by Tool identities (TOL-111) and
// PromptAssemblyRequest (P1-IS007 Rev1.1 Chapter 25.2).
//
// ModelInput is immutable for the inference operation and uses
// value semantics (Chapter 7).
//
// NON-responsibilities:
// - ModelInput references no Prompt, Memory, Context, Planner,
//   Tool, or Runtime object; it carries values only.
// ============================================================

#pragma once

#include <string>
#include <utility>

namespace ak::model {

// The immutable model-facing input for one inference operation.
class ModelInput final {
public:
    explicit ModelInput(std::string content);

    ModelInput(const ModelInput&) = default;
    ModelInput& operator=(const ModelInput&) = default;
    ModelInput(ModelInput&&) = default;
    ModelInput& operator=(ModelInput&&) = default;

    [[nodiscard]] const std::string& Content() const noexcept {
        return content_;
    }

private:
    std::string content_;
};

}  // namespace ak::model
