// ============================================================
// Agent Kernel - RuntimeObservation (Agent boundary)
// ============================================================
// TASK 2 §11 / TASK 3.1 §8.4 - Agent-owned observation value.
//
// RuntimeObservation is the minimum Agent-facing representation
// of ONE Runtime invocation outcome. It is NOT:
//   - a Runtime internal result object;
//   - an EventBus event;
//   - a new typed observation/event framework (TASK 2 §11.1).
//
// Successful output SHALL be associated with the specific
// invocation via request_id (TASK 2 §11.4). The Agent SHALL NOT
// infer an individual result from an unrelated session aggregate.
//
// Ownership: Agent boundary. No Runtime internal type crosses
// this value (TASK 2 §7.1).
// ============================================================

#pragma once

#include <cstdint>
#include <string>

#include <agent_kernel/agent/runtime/runtime_invocation_request.hpp>

namespace ak::agent {

// ============================================================
// ObservationStatus - terminal observation outcome
// ============================================================
enum class ObservationStatus : std::uint8_t {
    kSuccess = 0,  // invocation completed; output populated
    kFailure       // invocation failed or could not be observed
};

// ============================================================
// RuntimeObservation
// ============================================================
// Semantics:
//   kSuccess -> output carries the capability output; failure empty.
//   kFailure -> failure carries the deterministic failure
//               information; output empty.
// ============================================================
struct RuntimeObservation {
    RuntimeRequestId request_id;
    std::string capability_id;
    ObservationStatus status = ObservationStatus::kFailure;
    std::string output;
    std::string failure;
};

}  // namespace ak::agent
