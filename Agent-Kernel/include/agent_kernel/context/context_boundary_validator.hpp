// ============================================================
// Agent Kernel - ContextBoundaryValidator (Context boundary)
// ============================================================
// Context-owned ownership and dependency validation.
//
// P1-IS004 scope (Chapter 21 - Test Requirements, Chapter 27):
// - Validates the Context representation: identity, normative
//   lifecycle/operational states, per-Object state separation,
//   Object invariants, extension-boundary isolation, and
//   lifecycle/state distinctness.
// - The static include/link boundary is enforced by the CMake
//   Context boundary check (tests/context/
//   check_context_boundaries.cmake); this validator performs
//   executable representation-level validation.
//
// NON-responsibilities:
// - The validator owns no Context state and cannot initiate
//   lifecycle or operational transitions.
// ============================================================

#pragma once

#include <type_traits>

#include <agent_kernel/context/context.hpp>
#include <agent_kernel/foundation/kernel_diagnostics.hpp>

namespace ak::context {

class ContextBoundaryValidator {
public:
    ContextBoundaryValidator() = default;

    // Validates the Context representation and appends
    // diagnostics to the caller-provided owner-scoped sink.
    void Validate(const Context& context, ak::DiagnosticSink& sink) const;

    // Phase 2 static property: no concrete Runtime dependency
    // and no Runtime integration.
    [[nodiscard]] static constexpr bool Phase2HasNoConcreteRuntimeDependency() noexcept {
        return true;
    }

    // Compile-time separation proof: lifecycle and operational
    // state are distinct state models.
    static_assert(!std::is_same_v<ContextLifecycleState, ContextOperationalState>,
                  "lifecycle and operational state must remain distinct models");
};

}  // namespace ak::context
