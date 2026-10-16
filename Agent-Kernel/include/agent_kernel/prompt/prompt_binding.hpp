// ============================================================
// Agent Kernel - Prompt Input Bindings (Prompt boundary)
// ============================================================
// P1-IS007 Rev1.1 Chapter 12.2 - value-based input binding.
//
// PromptInputBinding binds an external value to a declared
// PromptVariable. Bindings are value-based (PRM-012): the
// bound value is a minimal immutable boundary value; Prompt
// SHALL NOT retain ownership of external Context, Memory,
// Planner, or Tool objects merely because their values were
// used during assembly (Chapter 12.2, PRM-037, TOL-022).
//
// NON-responsibilities:
// - The binding holds no reference to any source subsystem
//   object and transfers no ownership.
// ============================================================

#pragma once

#include <stdexcept>
#include <string>
#include <utility>

#include <agent_kernel/prompt/prompt_variable.hpp>

namespace ak::prompt {

// Binds an external value to a declared PromptVariable
// (Chapter 12.2). The variable name is validated at
// construction; an empty or whitespace-only name is a
// malformed binding and throws std::invalid_argument.
class PromptInputBinding final {
public:
    PromptInputBinding(std::string variable_name, std::string value);

    [[nodiscard]] const std::string& VariableName() const noexcept;
    [[nodiscard]] const std::string& Value() const noexcept;

private:
    std::string variable_name_;
    std::string value_;
};

}  // namespace ak::prompt