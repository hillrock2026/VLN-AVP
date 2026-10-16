// ============================================================
// lifecycle_diagnostics_test.cpp - P1-IS001 lifecycle/diagnostic
// ============================================================
// Verifies:
// - LifecycleState is a neutral state value representation.
// - LifecycleTransitionValidator requires an owner-supplied
//   rule and cannot independently initiate transitions.
// - Transition results report accept/reject outcomes.
// - DiagnosticSink is a neutral, owner-scoped collector.
// ============================================================

#include <agent_kernel/foundation/kernel_diagnostics.hpp>
#include <agent_kernel/foundation/kernel_lifecycle.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <type_traits>
#include <utility>

namespace ak {
namespace {

// ------------------------------------------------------------
// Owner-defined states and transition rule (test-local)
// ------------------------------------------------------------
namespace owner_states {
constexpr std::uint8_t kCreated = 0;
constexpr std::uint8_t kReady = 1;
constexpr std::uint8_t kTerminated = 2;
}  // namespace owner_states

// The owning subsystem defines what is legal. The Foundation
// only validates requests against this rule.
bool OwnerRule(std::uint8_t from, std::uint8_t to) noexcept {
    if (from == owner_states::kCreated && to == owner_states::kReady) {
        return true;
    }
    if (from == owner_states::kReady && to == owner_states::kTerminated) {
        return true;
    }
    return false;
}

// ------------------------------------------------------------
// LifecycleState
// ------------------------------------------------------------
TEST(LifecycleState, IsNeutralStateValue) {
    LifecycleState created(owner_states::kCreated);
    LifecycleState ready(owner_states::kReady);
    EXPECT_EQ(created.Value(), owner_states::kCreated);
    EXPECT_NE(created, ready);
    EXPECT_EQ(created, LifecycleState(owner_states::kCreated));
}

// ------------------------------------------------------------
// LifecycleTransitionValidator
// ------------------------------------------------------------
TEST(LifecycleTransitionValidator, ValidatesAgainstOwnerRule) {
    LifecycleTransitionValidator validator(OwnerRule);

    TransitionResult accepted = validator.Validate(
        owner_states::kCreated, owner_states::kReady);
    EXPECT_TRUE(accepted.Accepted());
    EXPECT_FALSE(accepted.Rejected());

    TransitionResult rejected = validator.Validate(
        owner_states::kCreated, owner_states::kTerminated);
    EXPECT_TRUE(rejected.Rejected());
    EXPECT_FALSE(rejected.Accepted());
}

TEST(LifecycleTransitionValidator, AcceptsLifecycleStateValues) {
    LifecycleTransitionValidator validator(OwnerRule);
    EXPECT_TRUE(validator.Validate(LifecycleState(owner_states::kCreated),
                                   LifecycleState(owner_states::kReady))
                    .Accepted());
}

TEST(LifecycleTransitionValidator, RejectsWithoutConfiguredRule) {
    LifecycleTransitionValidator validator(nullptr);
    TransitionResult result = validator.Validate(0, 1);
    EXPECT_TRUE(result.Rejected());
    EXPECT_NE(std::string(result.message), "");
}

template <typename T, typename = void>
struct HasAdvance : std::false_type {};
template <typename T>
struct HasAdvance<T, std::void_t<decltype(std::declval<T&>().Advance())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasTransition : std::false_type {};
template <typename T>
struct HasTransition<T, std::void_t<decltype(std::declval<T&>().Transition())>>
    : std::true_type {};

TEST(LifecycleTransitionValidator, CannotInitiateTransitionsByItself) {
    // The validator holds no lifecycle state and exposes no
    // transition-initiating API: the owner supplies both the
    // current value and the requested target value.
    static_assert(!HasAdvance<LifecycleTransitionValidator>::value,
                  "validator must not advance state by itself");
    static_assert(!HasTransition<LifecycleTransitionValidator>::value,
                  "validator must not perform transitions by itself");
    static_assert(!std::is_default_constructible_v<LifecycleTransitionValidator>,
                  "validator must require an owner-supplied rule");
}

// ------------------------------------------------------------
// DiagnosticSink
// ------------------------------------------------------------
TEST(DiagnosticSink, CollectsNeutralDiagnostics) {
    DiagnosticSink sink;
    EXPECT_EQ(sink.Count(), 0);
    EXPECT_FALSE(sink.HasErrors());

    sink.Add(DiagnosticSeverity::kInfo, 1, "info");
    sink.Add(DiagnosticSeverity::kWarning, 2, "warn");
    sink.Add(DiagnosticSeverity::kError, 3, "error");

    EXPECT_EQ(sink.Count(), 3);
    EXPECT_EQ(sink.ErrorCount(), 1);
    EXPECT_TRUE(sink.HasErrors());
    EXPECT_EQ(sink.All()[2].code, 3);
    EXPECT_TRUE(sink.All()[2].IsError());
    EXPECT_FALSE(sink.All()[0].IsError());
}

TEST(DiagnosticSink, ClearResetsCollection) {
    DiagnosticSink sink;
    sink.Add(DiagnosticSeverity::kError, 1, "e");
    sink.Clear();
    EXPECT_EQ(sink.Count(), 0);
    EXPECT_FALSE(sink.HasErrors());
}

}  // namespace
}  // namespace ak