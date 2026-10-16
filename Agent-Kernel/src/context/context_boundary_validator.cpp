// ============================================================
// Agent Kernel - ContextBoundaryValidator (Context boundary)
// ============================================================
// Implementation of Context-owned ownership/dependency
// validation.
// ============================================================

#include <agent_kernel/context/context_boundary_validator.hpp>

#include <agent_kernel/context/context.hpp>

namespace ak::context {

void ContextBoundaryValidator::Validate(const Context& context,
                                        ak::DiagnosticSink& sink) const {
    // Identity: Context must carry a valid, independently owned
    // identity.
    if (!context.GetIdentity().IsValid()) {
        sink.Add(ak::DiagnosticSeverity::kError, 60,
                 "Context identity is invalid");
    }

    // Lifecycle/operational separation is enforced at compile
    // time (distinct types) and at runtime by per-Object state
    // exposure through the Access Service.
    const auto objects = context.Access().ListObjects();
    if (!objects.IsSuccess()) {
        sink.Add(ak::DiagnosticSeverity::kError, 61,
                 "Context Object enumeration failed");
        return;
    }
    for (const ContextObjectId object_id : objects.value) {
        const auto view = context.Access().InspectObject(object_id);
        if (!view.IsSuccess()) {
            if (view.status == ContextResultStatus::kReleased) {
                // Released Objects reject operational access by design;
                // terminality is enforced by the state machines.
                continue;
            }
            sink.Add(ak::DiagnosticSeverity::kError, 62,
                     "Context Object inspection failed");
            continue;
        }
        // Invariant: a released lifecycle must coincide with a
        // released operational state (services drive both
        // dimensions in lockstep).
        const bool lifecycle_released =
            view.value.lifecycle == ContextLifecycleState::kReleased;
        const bool operational_released =
            view.value.operational == ContextOperationalState::kReleased;
        if (lifecycle_released != operational_released) {
            sink.Add(ak::DiagnosticSeverity::kError, 63,
                     "Context Object lifecycle/state consistency violation");
        }
        // Invariant: every released Object must be terminal in
        // both dimensions (already covered above).
        if (lifecycle_released || operational_released) {
            continue;
        }
        // Invariant: an active working state requires a prepared
        // lifecycle (Initialized or later).
        if (view.value.operational == ContextOperationalState::kActive &&
            view.value.lifecycle == ContextLifecycleState::kCreated) {
            sink.Add(ak::DiagnosticSeverity::kWarning, 64,
                     "Context Object is operationally Active while lifecycle "
                     "is Created");
        }
    }

    // Extensions: no foreign subsystem extension may attach to
    // the Context boundary.
    if (context.Extensions().ContainsForeignExtension()) {
        sink.Add(ak::DiagnosticSeverity::kError, 65,
                 "foreign extension attached to Context boundary");
    }
}

}  // namespace ak::context
