#pragma once

// ============================================================
// Agent Kernel — ExecutionResult (AK0036 Revision 2)
// ============================================================
// Canonical Runtime value object representing execution outcome.
//
// Fields:
//   status    — execution outcome classification
//   message   — human-readable diagnostic
//   output    — capability output (populated only for kCompleted)
//   retryable — whether the task may be retried
//
// ExecutionResult belongs to the Runtime layer.
// It is NOT stored inside Task.
// ============================================================

#include <cstdint>
#include <string>
#include <optional>
#include <any>

namespace ak {

// ============================================================
// ExecutionStatus — canonical Runtime execution status
// ============================================================
enum class ExecutionStatus : std::uint8_t {
    kCompleted = 0,      // Execution finished successfully
    kFailed,             // Execution finished with error
    kCancelled,          // Execution was cancelled
    kUnresolvable,       // Capability could not be resolved
    kInternalError       // Unexpected Runtime internal error
};

// ============================================================
// ExecutionResult — canonical execution outcome
// ============================================================
struct ExecutionResult {
    ExecutionStatus status = ExecutionStatus::kCompleted;
    // Optional canonical invocation identity (TASK 2 §9.2 / §17;
    // TASK 3.1 §9.4). Set by the Runtime Run loop from the
    // originating TaskExecutionDescriptor.request_id. Enables
    // per-invocation result retrieval via request_id.
    std::optional<std::string> request_id;
    std::string message;                       // Diagnostic message
    std::optional<std::any> output;            // Capability output (only for kCompleted)
    bool retryable = false;                    // Whether the task may be retried

    [[nodiscard]] bool IsSuccess() const noexcept {
        return status == ExecutionStatus::kCompleted;
    }

    [[nodiscard]] bool IsFailure() const noexcept {
        return status == ExecutionStatus::kFailed ||
               status == ExecutionStatus::kUnresolvable ||
               status == ExecutionStatus::kInternalError;
    }
};

}  // namespace ak