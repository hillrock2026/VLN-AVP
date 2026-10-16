// ============================================================
// Agent Kernel - KernelLifecycle (Foundation Layer)
// ============================================================
// Owner-controlled lifecycle mechanics.
//
// P1-IS001 Kernel Foundation scope:
// - KernelLifecycle provides neutral mechanics for state value
//   representation, transition validation, and transition
//   result reporting.
// - The owning subsystem SHALL define its states, define its
//   transition rules, and initiate its own transitions. The
//   Foundation only validates and reports.
//
// NON-responsibilities (P1-IS001):
// - KernelLifecycle does NOT determine when an architectural
//   lifecycle transition occurs.
// - It does NOT own, merge, or coordinate lifecycle domains
//   (Agent, Memory, Context, Planner, Tool, Runtime).
// - There is NO universal lifecycle manager here and no stored
//   lifecycle authority.
// - Lifecycle support remains owner-controlled.
// ============================================================

#pragma once

#include <cstdint>

namespace ak {

// ============================================================
// LifecycleState - neutral state value representation
// ============================================================
// A simple, owner-neutral state value. The owning subsystem
// maps its own state constants onto LifecycleState values;
// the Foundation attaches no meaning to the numeric value.
class LifecycleState {
public:
    using ValueType = std::uint8_t;

    explicit LifecycleState(ValueType value) noexcept : value_(value) {}

    [[nodiscard]] ValueType Value() const noexcept { return value_; }

    auto operator<=>(const LifecycleState&) const = default;

private:
    ValueType value_ = 0;
};

// ============================================================
// TransitionResult - transition outcome reporting
// ============================================================
enum class TransitionStatus : std::uint8_t {
    kAccepted,
    kRejected
};

struct TransitionResult {
    TransitionStatus status = TransitionStatus::kRejected;
    // Human-readable reason; valid for the lifetime of the
    // result. Prefer static storage.
    const char* message = "";

    [[nodiscard]] bool Accepted() const noexcept {
        return status == TransitionStatus::kAccepted;
    }

    [[nodiscard]] bool Rejected() const noexcept {
        return status == TransitionStatus::kRejected;
    }
};

// ============================================================
// LifecycleTransitionValidator - transition validation
// ============================================================
// Validates a transition request against an owner-supplied
// rule. The validator stores no state and cannot initiate a
// transition by itself: the owner supplies the current state,
// the requested target state, and the rule that defines what
// is legal.
class LifecycleTransitionValidator {
public:
    // Owner-supplied rule: returns true when the transition
    // from -> to is permitted by the owning subsystem.
    using Rule = bool (*)(std::uint8_t from, std::uint8_t to) noexcept;

    explicit LifecycleTransitionValidator(Rule rule) noexcept : rule_(rule) {}

    [[nodiscard]] TransitionResult Validate(LifecycleState from,
                                             LifecycleState to) const noexcept {
        return Validate(from.Value(), to.Value());
    }

    [[nodiscard]] TransitionResult Validate(std::uint8_t from,
                                             std::uint8_t to) const noexcept {
        if (rule_ == nullptr) {
            return {TransitionStatus::kRejected,
                    "no transition rule is configured"};
        }
        if (rule_(from, to)) {
            return {TransitionStatus::kAccepted, ""};
        }
        return {TransitionStatus::kRejected,
                "transition is not permitted by the owner rule"};
    }

private:
    Rule rule_;
};

}  // namespace ak