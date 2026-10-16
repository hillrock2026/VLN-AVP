// ============================================================
// Agent Kernel - MemoryBoundaryValidator (Memory boundary)
// ============================================================
// Implementation of Memory-owned ownership/dependency
// validation.
// ============================================================

#include <agent_kernel/memory/memory_boundary_validator.hpp>

#include <agent_kernel/foundation/kernel_diagnostics.hpp>
#include <agent_kernel/memory/memory.hpp>

namespace ak::memory {

void MemoryBoundaryValidator::Validate(const Memory& memory,
                                       ak::DiagnosticSink& sink) const {
    // Identity: Memory must carry a valid, independently owned
    // identity.
    if (!memory.GetIdentity().IsValid()) {
        sink.Add(ak::DiagnosticSeverity::kError, 30,
                 "Memory identity is invalid");
    }

    // Lifecycle: the exposed state must be normative.
    if (memory.GetLifecycleStateName() == "Unknown") {
        sink.Add(ak::DiagnosticSeverity::kError, 31,
                 "Memory lifecycle state is not normative");
    }

    // Operational state: the exposed state must be normative.
    if (memory.GetOperationalStateName() == "Unknown") {
        sink.Add(ak::DiagnosticSeverity::kError, 32,
                 "Memory operational state is not normative");
    }

    // Lifecycle/operational separation is enforced at compile
    // time (distinct types) and at runtime by independent state
    // exposure: both queries must remain independently readable.
    if (memory.GetLifecycleState() == MemoryLifecycleState::kActive &&
        memory.GetOperationalState() == MemoryOperationalState::kUnavailable) {
        sink.Add(ak::DiagnosticSeverity::kWarning, 33,
                 "Memory lifecycle is Active while operational state is "
                 "Unavailable; services are gated");
    }

    // Provider: Memory must own a provider (technology remains
    // subordinate).
    if (!memory.HasProvider()) {
        sink.Add(ak::DiagnosticSeverity::kError, 34,
                 "Memory owns no provider");
    }

    // Extensions: no foreign subsystem extension may attach to
    // the Memory boundary.
    if (memory.Extensions().ContainsForeignExtension()) {
        sink.Add(ak::DiagnosticSeverity::kError, 35,
                 "foreign extension attached to Memory boundary");
    }
}

}  // namespace ak::memory