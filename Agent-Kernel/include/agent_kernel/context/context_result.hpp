// ============================================================
// Agent Kernel - ContextResult (Context boundary)
// ============================================================
// Context-owned, implementation-independent result semantics.
//
// P1-IS004 scope (Chapter 19 - Error Model, Chapter 27):
// - Context service operations return an implementation-
//   independent result capable of distinguishing the required
//   failure categories:
//       invalid Context identity
//       invalid lifecycle transition
//       invalid state transition
//       Context Object not found
//       Context Object unavailable
//       Context Object already released
//       invalid update / invalid composition
//       ownership / service-boundary violation
//       unsupported operation
//       internal Context failure
// - A result is a value; it carries no ownership and cannot
//   transfer architectural ownership.
// - Normal architectural outcomes are not expressed through
//   exceptions.
//
// NON-responsibilities:
// - ContextResult is not a Runtime result and references no
//   Runtime type.
// - A result never becomes a lifecycle or state authority.
// ============================================================

#pragma once

#include <cstdint>

namespace ak::context {

enum class ContextResultStatus : std::uint8_t {
    kSuccess = 0,
    kRejected,      // invalid lifecycle/state transition, ownership or
                    // service-boundary violation, unsupported operation
    kUnavailable,   // Context Object not yet operationally available
    kInvalid,       // invalid Context identity, Object not found,
                    // invalid update, invalid composition
    kConflict,      // identity already registered
    kReleased,      // Context Object already released
    kFailure        // internal Context failure
};

// Status-only result.
struct ContextResult {
    ContextResultStatus status = ContextResultStatus::kFailure;
    // Human-readable reason; valid for the lifetime of the
    // result. Prefer static storage.
    const char* message = "";

    [[nodiscard]] bool IsSuccess() const noexcept {
        return status == ContextResultStatus::kSuccess;
    }

    [[nodiscard]] bool IsRejected() const noexcept {
        return status == ContextResultStatus::kRejected;
    }
};

// Result carrying a Context-owned value (e.g., a typed identity
// or an object view copy).
template <typename T>
struct ContextResultValue {
    ContextResultStatus status = ContextResultStatus::kFailure;
    const char* message = "";
    T value{};

    [[nodiscard]] bool IsSuccess() const noexcept {
        return status == ContextResultStatus::kSuccess;
    }

    [[nodiscard]] bool IsRejected() const noexcept {
        return status == ContextResultStatus::kRejected;
    }
};

}  // namespace ak::context
