// ============================================================
// Agent Kernel - MemoryResult (Memory boundary)
// ============================================================
// Memory-owned, implementation-independent result semantics.
//
// P1-IS003 scope (Chapter 15 - Error / Result Semantics):
// - Memory service operations return an implementation-
//   independent result capable of distinguishing:
//       Success / Rejected / Unavailable / Invalid / Conflict
//       / Failure
// - A result is a value; it carries no ownership and cannot
//   transfer architectural ownership.
// - Normal architectural outcomes are not expressed through
//   exceptions (P1-IS003 Chapter 15.6).
//
// NON-responsibilities:
// - MemoryResult is not a Runtime result and references no
//   Runtime type.
// - A result never becomes a lifecycle or state authority.
// ============================================================

#pragma once

#include <cstdint>

namespace ak::memory {

enum class MemoryResultStatus : std::uint8_t {
    kSuccess = 0,
    kRejected,
    kUnavailable,
    kInvalid,
    kConflict,
    kFailure
};

// Status-only result.
struct MemoryResult {
    MemoryResultStatus status = MemoryResultStatus::kFailure;
    // Human-readable reason; valid for the lifetime of the
    // result. Prefer static storage.
    const char* message = "";

    [[nodiscard]] bool IsSuccess() const noexcept {
        return status == MemoryResultStatus::kSuccess;
    }

    [[nodiscard]] bool IsRejected() const noexcept {
        return status == MemoryResultStatus::kRejected;
    }
};

// Result carrying a Memory-owned value (e.g., a typed identity
// or an object copy).
template <typename T>
struct MemoryResultValue {
    MemoryResultStatus status = MemoryResultStatus::kFailure;
    const char* message = "";
    T value{};

    [[nodiscard]] bool IsSuccess() const noexcept {
        return status == MemoryResultStatus::kSuccess;
    }

    [[nodiscard]] bool IsRejected() const noexcept {
        return status == MemoryResultStatus::kRejected;
    }
};

}  // namespace ak::memory