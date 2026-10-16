// ============================================================
// Agent Kernel - PlannerBoundaryValidator (Planner boundary)
// ============================================================
// Planner-owned ownership and dependency validation
// (P1-IS005 Rev5.1 Chapter 20.7; AK0044 Revision A).
//
// - Validates the Planner representation: identity, operational
//   projection, session/artifact retirement at Terminated, and
//   inspection unavailability after Terminated (MIN-001).
// - The static include/link boundary is enforced by the CMake
//   Planner boundary check (tests/planner/
//   check_planner_boundaries.cmake); this validator performs
//   executable representation-level validation.
//
// NON-responsibilities:
// - The validator owns no Planner state and cannot initiate
//   lifecycle transitions.
// ============================================================

#pragma once

#include <type_traits>

#include <agent_kernel/foundation/kernel_diagnostics.hpp>
#include <agent_kernel/planner/planner.hpp>

namespace ak::planner {

class PlannerBoundaryValidator {
public:
    PlannerBoundaryValidator() = default;

    // Validates the Planner representation and appends
    // diagnostics to the caller-provided owner-scoped sink.
    void Validate(const Planner& planner, ak::DiagnosticSink& sink) const;

    // Phase 3 static property: no concrete Runtime dependency
    // and no Runtime integration.
    [[nodiscard]] static constexpr bool Phase3HasNoConcreteRuntimeDependency() noexcept {
        return true;
    }

    // Compile-time separation proof: lifecycle and operational
    // state are distinct state models.
    static_assert(!std::is_same_v<PlannerLifecycleState, PlannerOperationalState>,
                  "lifecycle and operational state must remain distinct models");
};

}  // namespace ak::planner
