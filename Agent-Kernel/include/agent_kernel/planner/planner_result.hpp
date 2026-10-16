// ============================================================
// Agent Kernel - PlannerResult (Planner boundary)
// ============================================================
// Planner result vocabularies (P1-IS005 Rev5.1 Chapters 10.2,
// 12.1, 12.3, 17; AK0044 Revision A Sections 11-14).
//
// Scope:
// - PlannerLifecycleResult carries lifecycle participation
//   outcomes (accepted/rejected/busy/unavailable/failure).
// - PlanningAcceptance carries submission outcomes; a refused
//   submission creates no exchange and no result obligation.
// - PlanningResult is a PRODUCED TERMINAL OUTCOME of one
//   accepted request, with status vocabulary {kSuccess,kFailed}
//   only (Finding B closure); retirement and refusal outcomes
//   are completion-attempt outcomes, never PlanningResults.
// - PlanningCompletionResult is the single completion-attempt
//   response of CompletePlanningExchange; result is a valid
//   PlanningResult exactly when the attempt linearized.
// - PlannerInspectionResult carries inspection availability
//   (MIN-001: no Planner Service, including inspection, is
//   callable after Terminated).
//
// NON-responsibilities:
// - Results are values; they carry no ownership, no lifecycle
//   authority, and no Runtime semantics.
// - A result never transfers ownership of Planner-owned state.
// ============================================================

#pragma once

#include <cstdint>

#include <agent_kernel/planner/planner_identity.hpp>
#include <agent_kernel/planner/planner_state.hpp>
#include <agent_kernel/planner/planning_artifact.hpp>

namespace ak::planner {

// ------------------------------------------------------------
// Lifecycle participation result (Chapter 17)
// ------------------------------------------------------------
enum class PlannerLifecycleResultStatus : std::uint8_t {
    kAccepted = 0,   // transition committed
    kRejected,       // transition not permitted for the current lifecycle state
    kBusy,           // valid target but admission precondition fails (open exchanges)
    kUnavailable,    // operation not permitted (Terminating/Terminated or not yet created)
    kFailure         // internal failure
};

struct PlannerLifecycleResult {
    PlannerLifecycleResultStatus status = PlannerLifecycleResultStatus::kRejected;
    const char* message = "";
    PlannerLifecycleState target_state = PlannerLifecycleState::kCreated;

    [[nodiscard]] bool IsAccepted() const noexcept {
        return status == PlannerLifecycleResultStatus::kAccepted;
    }
};

// ------------------------------------------------------------
// Planning acceptance (Chapter 10.2)
// ------------------------------------------------------------
enum class PlanningAcceptanceStatus : std::uint8_t {
    kAccepted = 0,   // exchange opened; request copied into Planner-owned state
    kRefused,        // rejected before acceptance (invalid/duplicate request); no obligation
    kUnavailable     // Planner cannot accept (lifecycle not Ready/Planning, or Terminating/Terminated)
};

struct PlanningAcceptance {
    PlanningAcceptanceStatus status = PlanningAcceptanceStatus::kRefused;
    const char* message = "";
    PlanningRequestId request_id;
    PlannerSessionId session_id;

    [[nodiscard]] bool IsAccepted() const noexcept {
        return status == PlanningAcceptanceStatus::kAccepted;
    }
};

// ------------------------------------------------------------
// Terminal planning result (Chapter 12.1) - Finding B
// ------------------------------------------------------------
enum class PlanningResultStatus : std::uint8_t {
    kSuccess = 0,   // planning completed; artifact view delivered
    kFailed         // planning failed; failure reason delivered; no artifact
};

struct PlanningResult {
    PlanningResultId result_id;            // Planner-assigned at linearization
    PlanningRequestId request_id;          // one-to-one correlation with the accepted request
    PlannerSessionId session_id;
    PlanningResultStatus status = PlanningResultStatus::kFailed;
    const char* message = "";              // static failure reason or description
    PlanningArtifactView artifact_view;    // valid only when status == kSuccess

    [[nodiscard]] bool IsSuccess() const noexcept {
        return status == PlanningResultStatus::kSuccess;
    }

    [[nodiscard]] bool IsValid() const noexcept {
        return result_id.IsValid() && request_id.IsValid();
    }
};

// ------------------------------------------------------------
// Completion attempt result (Chapter 12.3)
// ------------------------------------------------------------
enum class PlanningCompletionStatus : std::uint8_t {
    kSuccess = 0,         // linearization; terminal result delivered and transferred
    kPending,             // open exchange, outcome not yet available; exchange preserved
    kSuspended,           // open exchange while Planner suspended; exchange preserved
    kRejectedDuplicate,   // exchange already retired; no second result
    kRejectedInvalid,     // unknown request id / inactive session; no exchange
    kRejectedTerminated   // Planner already Terminated (defensive; the host refuses earlier)
};

struct PlanningCompletionResult {
    PlanningCompletionStatus status = PlanningCompletionStatus::kPending;
    const char* message = "";
    PlanningResult result;                 // valid only when status == kSuccess

    [[nodiscard]] bool IsSuccess() const noexcept {
        return status == PlanningCompletionStatus::kSuccess;
    }

    [[nodiscard]] bool HasResult() const noexcept {
        return result.IsValid();
    }
};

// ------------------------------------------------------------
// Inspection result (Chapter 7.2; MIN-001)
// ------------------------------------------------------------
enum class PlannerInspectionStatus : std::uint8_t {
    kAvailable = 0,   // Planner operational; projection delivered
    kUnavailable      // Planner Terminated; service unavailable (AK0044 Revision A Section 7.3)
};

struct PlannerInspectionResult {
    PlannerInspectionStatus status = PlannerInspectionStatus::kUnavailable;
    const char* message = "";
    PlannerOperationalState operational = PlannerOperationalState::kCreated;

    [[nodiscard]] bool IsAvailable() const noexcept {
        return status == PlannerInspectionStatus::kAvailable;
    }
};

}  // namespace ak::planner
