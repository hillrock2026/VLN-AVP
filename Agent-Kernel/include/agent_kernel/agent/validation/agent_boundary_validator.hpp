// ============================================================
// Agent Kernel - AgentBoundaryValidator (Agent boundary)
// ============================================================
// Agent-owned ownership and dependency validation.
//
// P1-IS002 scope (Chapter 15.7, Chapter 26 - Architecture Test
// Model, Chapter 29 - Implementation Deliverables):
// - Phase 1 SHALL statically validate that Agent-side
//   implementation does not depend upon Runtime internals.
// - Ownership and dependency validation SHALL confirm:
//     * Agent identity validity;
//     * the single architectural state model;
//     * exactly the four peer subsystem contracts bound;
//     * the Runtime interaction port is contract-only;
//     * no subsystem extension attached to the Agent-specific
//       extension boundary.
//
// The static include/link boundary is enforced by the CMake
// boundary check (tests/agent/check_agent_boundaries.cmake);
// this validator performs the executable representation-level
// validation.
// ============================================================

#pragma once

#include <cstdint>

#include <agent_kernel/agent/agent.hpp>
#include <agent_kernel/foundation/kernel_diagnostics.hpp>

namespace ak::agent {

class AgentBoundaryValidator {
public:
    AgentBoundaryValidator() = default;

    // Validates the Agent representation and appends
    // diagnostics to the caller-provided owner-scoped sink.
    void Validate(const Agent& agent, ak::DiagnosticSink& sink) const;

    // Phase 1 static property: no concrete Runtime dependency.
    [[nodiscard]] static constexpr bool Phase1HasNoConcreteRuntimeDependency() noexcept {
        return true;
    }
};

}  // namespace ak::agent
