// ============================================================
// Agent Kernel - Prompt Assembly Request (Prompt boundary)
// ============================================================
// P1-IS007 Rev1.1 Chapter 13.1 - immutable assembly inputs.
//
// PromptAssemblyRequest carries the immutable input values for
// a single assembly operation: Agent instruction material,
// user input, Context/Memory/Planner/Tool-derived material, and
// additional application-provided material (Chapter 13.1,
// PRM-036).
//
// The request contains values or immutable views only; it SHALL
// NOT transfer ownership of source subsystems to Prompt
// (PRM-037, TOL-022). Duplicate binding names are malformed
// input and are rejected at construction with
// std::invalid_argument (Chapters 25.2, 41.4 - invalid input).
//
// NON-responsibilities:
// - The request performs no retrieval and references no source
//   subsystem object.
// ============================================================

#pragma once

#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <agent_kernel/prompt/prompt_binding.hpp>
#include <agent_kernel/prompt/prompt_section.hpp>

namespace ak::prompt {

// The immutable input values required for one assembly
// operation (Chapter 13.1). Immutable after construction
// (Chapter 17).
class PromptAssemblyRequest final {
public:
    PromptAssemblyRequest(std::vector<PromptInputBinding> bindings = {},
                          PromptMetadata metadata = {});

    [[nodiscard]] const std::vector<PromptInputBinding>& Bindings() const noexcept;
    [[nodiscard]] const PromptMetadata& Metadata() const noexcept;

private:
    std::vector<PromptInputBinding> bindings_;
    PromptMetadata metadata_;
};

}  // namespace ak::prompt