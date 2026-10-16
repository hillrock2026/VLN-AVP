// ============================================================
// Agent Kernel - ModelInput implementation (Model boundary)
// ============================================================
// P1-IS008 Rev1.0 Chapters 7, 14. Construction rejects empty or
// whitespace-only model-facing content with
// std::invalid_argument (InvalidInput category). The Model
// consumes only this immutable model-facing input; it never
// assembles input from Memory, Context, Planner, Tool, or
// Runtime (Chapter 12).
// ============================================================

#include <agent_kernel/model/model_input.hpp>

#include <algorithm>
#include <cctype>
#include <stdexcept>
#include <utility>

namespace ak::model {
namespace {

bool HasNonWhitespace(const std::string& value) noexcept {
    return std::any_of(value.begin(), value.end(), [](unsigned char c) {
        return !std::isspace(c);
    });
}

}  // namespace

ModelInput::ModelInput(std::string content) : content_(std::move(content)) {
    if (!HasNonWhitespace(content_)) {
        throw std::invalid_argument(
            "ModelInput content must be non-empty and contain at least one "
            "non-whitespace character (invalid input)");
    }
}

}  // namespace ak::model
