// ============================================================
// Agent Kernel - RuntimePublicApiAdapter (integration layer)
// ============================================================
// TASK 2 §13 / TASK 3.1 §8.6 - the sanctioned translation
// boundary between Agent-owned integration values and the
// Runtime Public API.
//
// This is the ONLY Agent -> Runtime integration path
// (T3.2-AC-005). It implements ak::agent::RuntimeInteractionPort.
//
// Responsibilities (TASK 2 §13.2):
//   1. receive RuntimeInvocationRequest;
//   2. validate required request information;
//   3. preserve request_id;
//   4. translate capability identity (A1 translation point);
//   5. transport payload;
//   6. submit through Runtime Public API;
//   7. obtain the specific invocation result;
//   8. map result into RuntimeObservation;
//   9. map Runtime failure into deterministic Agent-visible failure;
//  10. prevent Runtime internal types from crossing the Agent
//      boundary.
//
// Ownership: integration layer. Not Agent (Agent stays
// Runtime-free), not Runtime (Runtime stays Agent-free).
//
// Boundary: the Agent sees only RuntimeInteractionPort. Scheduler,
// Executor, CapabilityResolver, EventBus, and Runtime internal
// types never cross the Agent boundary (TASK 2 §8.3 / §13.2.10).
// This header therefore contains no Runtime include; the only
// Runtime reference is a forward declaration.
//
// A1 governance decision (TASK 3.2): the exact capability
// identity translation (Agent contract capability_id ->
// Runtime-side descriptor.capability.name) happens in Submit().
// ============================================================

#pragma once

#include <cstdint>
#include <functional>
#include <string>
#include <unordered_map>

#include <agent_kernel/agent/runtime/runtime_interaction_port.hpp>
#include <agent_kernel/agent/runtime/runtime_invocation_request.hpp>
#include <agent_kernel/agent/runtime/runtime_observation.hpp>
#include <agent_kernel/agent/runtime/runtime_submission_result.hpp>

namespace ak::runtime {

// Forward declaration only: no Runtime internal type is exposed
// through this header (TASK 2 §13.2.10).
class Runtime;

}  // namespace ak::runtime

namespace ak::runtime_integration {

// ============================================================
// RuntimePublicApiAdapter
// ============================================================
// Concrete implementation of the Agent-owned Runtime contract.
// The base-port defaults (contract-level rejected / not-
// observable) are overridden here; actual Runtime interaction
// happens ONLY in this class (B1 governance decision).
class RuntimePublicApiAdapter final : public ak::agent::RuntimeInteractionPort {
public:
    // Non-owning Runtime reference; Runtime MUST outlive the
    // adapter (TASK 3.1 §13 API table).
    explicit RuntimePublicApiAdapter(ak::runtime::Runtime& runtime) noexcept;

    // Registers a capability that Submit() bootstraps onto the
    // Runtime before its first invocation (TASK 3.1 §17). The
    // invoker is the actual executable capability (TASK 2 §14).
    void RegisterCapability(
        std::string name,
        std::string provider,
        std::function<std::string(const std::string&)> invoker);

    // TASK 2 §8.2: submit one RuntimeInvocationRequest and return
    // the terminal submission outcome (completed/rejected/failed).
    [[nodiscard]] ak::agent::RuntimeSubmissionResult Submit(
        const ak::agent::RuntimeInvocationRequest& request) override;

    // TASK 2 §8.2: observe the per-invocation outcome for
    // request_id (TASK 2 §17; request_id is the canonical
    // invocation identity).
    [[nodiscard]] ak::agent::RuntimeObservation Observe(
        const ak::agent::RuntimeRequestId& request_id) override;

private:
    struct RegisteredCapability {
        std::string provider;
        std::function<std::string(const std::string&)> invoker;
    };

    ak::runtime::Runtime& runtime_;

    // Adapter-owned bootstrap capability table: capability_id ->
    // registered executable capability (never a Runtime registry).
    std::unordered_map<std::string, RegisteredCapability> capabilities_;

    // request_id -> capability_id: preserves the capability
    // identity across Submit -> Observe so the per-invocation
    // RuntimeObservation can carry the Agent-owned capability_id.
    std::unordered_map<std::string, std::string> submitted_capabilities_;

    // request_id -> deterministic failure reason for submissions
    // that terminate before/without a stored Runtime per-invocation
    // result (rejected or failed), so Observe maps them to the same
    // deterministic failure (TASK 3.1 §19).
    std::unordered_map<std::string, std::string> submission_failures_;

    // Deterministic session identity counter for the one-shot
    // Session per submission.
    std::uint64_t session_counter_ = 0;
};

}  // namespace ak::runtime_integration