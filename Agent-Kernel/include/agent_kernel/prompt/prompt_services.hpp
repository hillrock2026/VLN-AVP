// ============================================================
// Agent Kernel - Prompt Services (Prompt boundary)
// ============================================================
// P1-IS007 Rev1.1 Chapter 24 - the primary Prompt service.
//
// PromptAssemblyService is the single production assembly
// operation (PRM-040, Chapters 24.1, 41.1): no partial,
// incremental, streaming, or subsystem-specific assembly
// operations exist.
//
// The service is owned by the Prompt root (PRM-019) and
// remains valid while its owning Prompt exists (PRM-020,
// Chapter 24.3). The service is stateless (PRM-044): no hidden
// cache, mutable history, Prompt memory, or global assembly
// state exists.
//
// NON-responsibilities:
// - The service performs no retrieval, no Model call, and no
//   Runtime call (PRM-036, PRM-029).
// ============================================================

#pragma once

#include <agent_kernel/prompt/prompt_request.hpp>
#include <agent_kernel/prompt/prompt_result.hpp>

namespace ak::prompt {

// The primary Prompt service (Chapter 24.1).
class PromptAssemblyService {
public:
    virtual ~PromptAssemblyService() = default;

    // The single production assembly operation. Deterministic
    // for equivalent inputs (PRM-014, Chapter 41.2); side-
    // effect free with respect to all external Agent Kernel
    // subsystems (PRM-036, Chapter 25.4).
    [[nodiscard]] virtual PromptAssemblyResult Assemble(
        const PromptAssemblyRequest& request) const = 0;
};

}  // namespace ak::prompt