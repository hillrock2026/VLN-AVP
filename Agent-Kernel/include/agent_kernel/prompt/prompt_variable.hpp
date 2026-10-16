// ============================================================
// Agent Kernel - Prompt Variables (Prompt boundary)
// ============================================================
// P1-IS007 Rev1.1 Chapter 12.1 - declared Prompt inputs.
//
// A PromptVariable declares a named input required by Prompt
// assembly with a stable name, an expected semantic category,
// and a required/optional status (PRM-011). Variable
// definitions are immutable after construction (Chapter 17).
//
// NON-responsibilities:
// - A variable is an assembly declaration; it references no
//   source subsystem object and transfers no ownership
//   (PRM-037).
// ============================================================

#pragma once

#include <algorithm>
#include <cctype>
#include <stdexcept>
#include <string>
#include <utility>

#include <agent_kernel/prompt/prompt_section.hpp>

namespace ak::prompt {

namespace detail {

// Variable names must be non-empty and contain at least one
// non-whitespace character (Chapter 25.1).
inline bool IsValidVariableName(const std::string& name) noexcept {
    return std::any_of(name.begin(), name.end(),
                       [](unsigned char c) { return !std::isspace(c); });
}

inline void ValidateVariableName(const std::string& name) {
    if (!IsValidVariableName(name)) {
        throw std::invalid_argument(
            "Prompt variable name must be non-empty and contain "
            "at least one non-whitespace character");
    }
}

}  // namespace detail

// A named input required by Prompt assembly (Chapter 12.1).
class PromptVariable final {
public:
    PromptVariable(std::string name,
                   PromptSectionKind category,
                   bool required);

    [[nodiscard]] const std::string& Name() const noexcept;
    [[nodiscard]] PromptSectionKind Category() const noexcept;
    [[nodiscard]] bool Required() const noexcept;

private:
    std::string name_;
    PromptSectionKind category_;
    bool required_;
};

}  // namespace ak::prompt