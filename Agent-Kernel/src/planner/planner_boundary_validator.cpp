// ============================================================
// Agent Kernel - PlannerBoundaryValidator (Planner boundary)
// ============================================================
// Implementation of Planner-owned representation-level
// ownership/dependency validation.
// ============================================================

#include <agent_kernel/planner/planner_boundary_validator.hpp>

#include <agent_kernel/planner/planner.hpp>

namespace ak::planner {

void PlannerBoundaryValidator::Validate(const Planner& planner,
                                        ak::DiagnosticSink& sink) const {
    // Identity: Planner must carry a valid, independently owned
    // identity.
    if (!planner.GetIdentity().IsValid()) {
        sink.Add(ak::DiagnosticSeverity::kError, 70,
                 "Planner identity is invalid");
    }

    // Invariant: Operational State is the deterministic 1:1
    // projection of lifecycle state in every state.
    const PlannerState state = planner.GetState();
    if (state.operational != ProjectOperationalState(state.lifecycle)) {
        sink.Add(ak::DiagnosticSeverity::kError, 71,
                 "Planner operational state is not the deterministic "
                 "projection of lifecycle state");
    }

    // Invariant: at Terminated the primary session and every
    // Planner-owned artifact/execution plan are retired.
    if (state.lifecycle == PlannerLifecycleState::kTerminated) {
        if (state.session_count != 0) {
            sink.Add(ak::DiagnosticSeverity::kError, 72,
                     "Planner session must be retired at Terminated");
        }
        if (state.active_artifact_count != 0) {
            sink.Add(ak::DiagnosticSeverity::kError, 73,
                     "Planner artifacts must be retired at Terminated");
        }
        // MIN-001: PlannerInspectionService SHALL be unavailable
        // after Terminated (AK0044 Revision A Section 7.3).
        const PlannerInspectionResult inspection =
            planner.Inspection().GetOperationalState();
        if (inspection.status != PlannerInspectionStatus::kUnavailable) {
            sink.Add(ak::DiagnosticSeverity::kError, 74,
                     "PlannerInspectionService must be unavailable "
                     "after Terminated");
        }
    }

    // Extensions: no foreign subsystem extension may attach to
    // the Planner boundary.
    if (planner.Extensions().ContainsForeignExtension()) {
        sink.Add(ak::DiagnosticSeverity::kError, 75,
                 "foreign extension attached to Planner boundary");
    }
}

}  // namespace ak::planner
