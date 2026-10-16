// ============================================================
// Agent Kernel - AgentBoundaryValidator (Agent boundary)
// ============================================================
// Implementation of Agent-owned ownership/dependency
// validation.
// ============================================================

#include <agent_kernel/agent/validation/agent_boundary_validator.hpp>

#include <agent_kernel/agent/agent.hpp>
#include <agent_kernel/foundation/kernel_diagnostics.hpp>

namespace ak::agent {

void AgentBoundaryValidator::Validate(const Agent& agent,
                                      ak::DiagnosticSink& sink) const {
    // Identity: the Agent must carry a valid, independently
    // owned identity.
    if (!agent.GetIdentity().IsValid()) {
        sink.Add(ak::DiagnosticSeverity::kError, 20,
                 "Agent identity is invalid");
    }

    // State: the Agent exposes exactly one architectural state.
    const std::string_view state_name = agent.GetStateName();
    if (state_name == "Unknown") {
        sink.Add(ak::DiagnosticSeverity::kError, 21,
                 "Agent state is not an architectural state");
    }

    // Coordination: all four peer subsystem contracts bound.
    if (!agent.HasAllSubsystemContracts()) {
        sink.Add(ak::DiagnosticSeverity::kError, 22,
                 "not all peer subsystem contracts are bound");
    }

    // Runtime: Phase 1 port/contract only, no concrete Runtime
    // dependency.
    if (!agent.RuntimePort().IsContractOnly()) {
        sink.Add(ak::DiagnosticSeverity::kError, 23,
                 "Runtime interaction port is not contract-only");
    }

    // Extensions: no subsystem extension attached to the
    // Agent-specific extension boundary.
    if (agent.Extensions().ContainsSubsystemExtension()) {
        sink.Add(ak::DiagnosticSeverity::kError, 24,
                 "subsystem extension attached to Agent boundary");
    }

    // Composition: representation validation.
    if (!agent.Composition().Validate()) {
        sink.Add(ak::DiagnosticSeverity::kError, 25,
                 "execution composition representation is invalid");
    }
}

}  // namespace ak::agent
