// ============================================================
// Agent Kernel - RuntimeSubmissionResult (Agent boundary)
// ============================================================
// TASK 2 §10 / TASK 3.1 §8.3 - Agent-owned submission outcome.
//
// RuntimeSubmissionResult represents the terminal submission
// outcome of one RuntimeInvocationRequest. It is NOT capability
// output; capability output belongs to RuntimeObservation
// (TASK 2 §10).
//
// Minimum bounded synchronous cycle (F-002 CLOSED): submit MAY
// transition directly to a terminal status (completed/rejected/
// failed); an intermediate "accepted" state is NOT required.
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
// SubmissionStatus - terminal submission outcome
// ============================================================
enum class SubmissionStatus : std::uint8_t {
    kCompleted = 0,  // submission executed to a terminal outcome
    kRejected,       // submission rejected before execution
    kFailed          // submission accepted; execution failed
};

// ============================================================
// RuntimeSubmissionResult
// ============================================================
// Semantics:
//   kRejected -> accepted == false; failure carries the reason.
//   kCompleted -> accepted == true; failure empty.
//   kFailed    -> accepted == true; failure carries the reason.
// ============================================================
struct RuntimeSubmissionResult {
    RuntimeRequestId request_id;
    bool accepted = false;
    SubmissionStatus status = SubmissionStatus::kRejected;
    std::string failure;
};

}  // namespace ak::agent
