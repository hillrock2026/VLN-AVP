// ============================================================
// Agent Kernel - RuntimeInvocationRequest (Agent boundary)
// ============================================================
// TASK 2 §9 / TASK 3.1 §8.2 - Agent-owned invocation value.
//
// RuntimeInvocationRequest represents one Agent-requested
// Runtime capability invocation:
//
//   RuntimeRequestId request_id;   canonical invocation identity
//   std::string      capability_id; Agent-owned capability identity
//   std::string      payload;      invocation payload (TASK 2 §9.4)
//
// Ownership: Agent boundary. No Runtime internal type crosses
// this value (TASK 2 §7.1).
//
// A1 governance decision (TASK 3.2): capability identity is an
// Agent-owned opaque string. This header SHALL NOT include
// Tool or Runtime headers. RuntimePublicApiAdapter performs the
// exact translation from this Agent contract identity to the
// Runtime-side capability identity.
// ============================================================

#pragma once

#include <algorithm>
#include <cctype>
#include <stdexcept>
#include <string>
#include <utility>

namespace ak::agent {

namespace detail {

// Agent-owned identity values must be non-empty and contain at
// least one non-whitespace character.
inline bool IsNonEmptyIdentityValue(const std::string& value) noexcept {
    return std::any_of(value.begin(), value.end(),
                       [](unsigned char c) { return !std::isspace(c); });
}

}  // namespace detail

// ============================================================
// RuntimeRequestId - canonical invocation identity
// ============================================================
// TASK 2 §8.2 / §9.2 (F-003 CLOSED): request_id is the canonical
// invocation identity:
//
//   request_id -> specific invocation -> specific result/observation
//
// It is NOT a Session identity, Workflow identity, Task identity,
// Event ID, Scheduler ID, or Executor internal ID (TASK 2 §8.2).
//
// Minimal string-backed value type with non-empty validation.
// ============================================================
class RuntimeRequestId {
public:
    RuntimeRequestId() = delete;

    explicit RuntimeRequestId(std::string value) : value_(std::move(value)) {
        if (!detail::IsNonEmptyIdentityValue(value_)) {
            throw std::invalid_argument(
                "RuntimeRequestId must be non-empty and contain at "
                "least one non-whitespace character (TASK 2 §9.2)");
        }
    }

    [[nodiscard]] const std::string& Value() const noexcept { return value_; }

    friend bool operator==(const RuntimeRequestId&,
                           const RuntimeRequestId&) = default;

private:
    std::string value_;
};

// ============================================================
// RuntimeInvocationRequest
// ============================================================
// One Agent-requested Runtime capability invocation.
// request_id is the canonical invocation identity; payload is an
// opaque integration value that MUST reach the actual capability
// invocation boundary without silent loss (TASK 2 §15).
// ============================================================
struct RuntimeInvocationRequest {
    RuntimeRequestId request_id;
    std::string capability_id;
    std::string payload;
};

}  // namespace ak::agent
