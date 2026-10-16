// ============================================================
// Agent Kernel - RuntimeInteractionPort (Agent boundary)
// ============================================================
// Agent-owned Runtime interaction port/contract.
//
// P1-IS002 scope (Chapter 15 - Runtime Integration):
// - Phase 1 SHALL establish an Agent-owned Runtime interaction
//   port/contract that represents the Agent-side boundary for
//   future Runtime interaction, confines future interaction to
//   the Runtime Public API, exposes no Runtime internal type,
//   and enables static dependency/isolation validation.
// - The port represents "Runtime interaction, not Runtime
//   ownership" and SHALL NOT implement Runtime behavior.
//
// TASK 2 §8 (Minimum Runtime Integration Contract):
//   submit(RuntimeInvocationRequest) -> RuntimeSubmissionResult
//   observe(request_id)              -> RuntimeObservation
//
// B1 governance decision (TASK 3.2): the port remains a
// concrete contract-bearing base with SAFE DEFAULT virtual
// implementations (contract-level rejected / not-observable
// semantics). The defaults access NO Runtime, Scheduler,
// Executor, CapabilityResolver, EventBus, or Runtime registry,
// and depend on no Runtime internal type. RuntimePublicApiAdapter
// (integration layer) derives from this port and overrides
// Submit/Observe; actual Runtime interaction happens ONLY there.
//
// NON-responsibilities:
// - This port exposes NO Runtime type and performs NO Runtime
//   action. The Runtime Public API remains the authoritative
//   and exclusive future Agent-Runtime integration boundary.
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <string_view>

#include <agent_kernel/agent/runtime/runtime_invocation_request.hpp>
#include <agent_kernel/agent/runtime/runtime_observation.hpp>
#include <agent_kernel/agent/runtime/runtime_submission_result.hpp>

namespace ak::agent {

class RuntimeInteractionPort {
public:
    RuntimeInteractionPort() noexcept = default;

    virtual ~RuntimeInteractionPort() = default;

    RuntimeInteractionPort(const RuntimeInteractionPort&) = default;
    RuntimeInteractionPort& operator=(const RuntimeInteractionPort&) = default;
    RuntimeInteractionPort(RuntimeInteractionPort&&) = default;
    RuntimeInteractionPort& operator=(RuntimeInteractionPort&&) = default;

    // The authoritative future Agent-Runtime integration
    // boundary, expressed as the Phase 1 contract.
    [[nodiscard]] static constexpr std::string_view RuntimePublicApiBoundary() noexcept {
        return "Runtime Public API";
    }

    // Phase 1 contract status: the port is contract-only.
    [[nodiscard]] static constexpr bool IsContractOnly() noexcept { return true; }

    // Phase 1 contract version of the Agent-owned port.
    [[nodiscard]] static constexpr std::uint16_t ContractVersion() noexcept {
        return 1;
    }

    // --------------------------------------------------------
    // Minimum operational surface (TASK 2 §8.2).
    //
    // Default implementations are contract-level safe: they
    // perform no Runtime interaction. B1 governance decision:
    // the port stays concrete; RuntimePublicApiAdapter overrides
    // these operations with the sanctioned Runtime interaction.
    // --------------------------------------------------------

    // Submits one RuntimeInvocationRequest and returns the
    // terminal submission outcome. Default: rejected (the base
    // port is contract-only and performs no Runtime action).
    [[nodiscard]] virtual RuntimeSubmissionResult Submit(
        const RuntimeInvocationRequest& request) {
        (void)request;
        return RuntimeSubmissionResult{
            RuntimeRequestId("contract-only"),
            false,
            SubmissionStatus::kRejected,
            "contract-only port: submission is not implemented"};
    }

    // Observes the per-invocation outcome for request_id.
    // Default: not-observable failure (the base port performs
    // no Runtime action).
    [[nodiscard]] virtual RuntimeObservation Observe(
        const RuntimeRequestId& request_id) {
        (void)request_id;
        return RuntimeObservation{
            RuntimeRequestId("contract-only"),
            "",
            ObservationStatus::kFailure,
            "",
            "contract-only port: observation is not available"};
    }

private:
    // Intentionally empty: no Runtime types and no submission /
    // observation / translation state.
};

}  // namespace ak::agent
