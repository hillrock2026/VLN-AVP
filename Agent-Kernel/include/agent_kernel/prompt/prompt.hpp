// ============================================================
// Agent Kernel - Prompt Root (Prompt boundary)
// ============================================================
// P1-IS007 Rev1.1 Chapters 16, 24 - the canonical Prompt root.
//
// Prompt owns Prompt identity, the immutable PromptDefinition,
// and the Prompt-owned PromptAssemblyService (PRM-002,
// PRM-019). Construction establishes identity, the immutable
// definition, and validation of structural invariants
// (Chapter 16.2); invalid definitions are rejected during
// construction (Chapter 25.1).
//
// Prompt lifecycle is object lifetime, not an independent
// lifecycle state machine (Chapter 16.1, PRM-018): there is no
// Terminated state, and constructing the Prompt root is
// ordinary object construction, not subsystem lifecycle
// authority (Chapters 16.2, 19.3, PRM-048).
//
// Assembly is an independent const operation against immutable
// Prompt state; the implementation requires no synchronization
// because no shared mutable state exists (Chapters 17-18,
// PRM-021, PRM-044).
//
// NON-responsibilities:
// - Prompt performs no active retrieval from Memory, Context,
//   Planner, Tool, or Runtime (PRM-036, Chapter 7.8).
// - Prompt does not coordinate Agent, Model, or Runtime
//   (PRM-003, PRM-008, PRM-029).
// ============================================================

#pragma once

#include <memory>

#include <agent_kernel/prompt/prompt_definition.hpp>
#include <agent_kernel/prompt/prompt_identity.hpp>
#include <agent_kernel/prompt/prompt_services.hpp>

namespace ak::prompt {

// The canonical Prompt root (Chapters 16, 24).
class Prompt final {
public:
    // Ordinary object construction (Chapter 16.2). Rejects
    // invalid definitions (Chapter 25.1).
    explicit Prompt(PromptDefinition definition);

    Prompt(const Prompt&) = delete;
    Prompt& operator=(const Prompt&) = delete;
    Prompt(Prompt&&) = delete;
    Prompt& operator=(Prompt&&) = delete;

    ~Prompt();

    // -- identity / definition (immutable, read-only) --
    [[nodiscard]] const PromptId& Id() const noexcept;
    [[nodiscard]] const PromptDefinition& Definition() const noexcept;

    // -- Prompt-owned services (PRM-019, PRM-020) --
    [[nodiscard]] PromptAssemblyService& Assembly() noexcept;
    [[nodiscard]] const PromptAssemblyService& Assembly() const noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace ak::prompt