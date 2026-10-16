// ============================================================
// model_state_test.cpp - P1-IS008 Rev1.0 Chapter 10
// ============================================================
// Model lifecycle state tests: the four retained states
// (Uninitialized, Ready, Unavailable, Shutdown), normative
// transition table, and Foundation-validated transitions.
// ============================================================

#include <agent_kernel/model/model_state.hpp>

#include <gtest/gtest.h>

#include <string_view>

namespace ak::model {
namespace {

TEST(ModelState, StateNames) {
    EXPECT_EQ(ModelLifecycleStateName(ModelLifecycleState::kUninitialized),
              "Uninitialized");
    EXPECT_EQ(ModelLifecycleStateName(ModelLifecycleState::kReady), "Ready");
    EXPECT_EQ(ModelLifecycleStateName(ModelLifecycleState::kUnavailable),
              "Unavailable");
    EXPECT_EQ(ModelLifecycleStateName(ModelLifecycleState::kShutdown),
              "Shutdown");
}

TEST(ModelState, StateCodesAreStable) {
    EXPECT_EQ(ModelLifecycleStateCode(ModelLifecycleState::kUninitialized), 0u);
    EXPECT_EQ(ModelLifecycleStateCode(ModelLifecycleState::kReady), 1u);
    EXPECT_EQ(ModelLifecycleStateCode(ModelLifecycleState::kUnavailable), 2u);
    EXPECT_EQ(ModelLifecycleStateCode(ModelLifecycleState::kShutdown), 3u);
}

TEST(ModelState, LegalTransitions) {
    EXPECT_TRUE(IsLegalModelLifecycleTransition(
        ModelLifecycleState::kUninitialized, ModelLifecycleState::kReady));
    EXPECT_TRUE(IsLegalModelLifecycleTransition(
        ModelLifecycleState::kUninitialized, ModelLifecycleState::kUnavailable));
    EXPECT_TRUE(IsLegalModelLifecycleTransition(
        ModelLifecycleState::kReady, ModelLifecycleState::kShutdown));
    EXPECT_TRUE(IsLegalModelLifecycleTransition(
        ModelLifecycleState::kUnavailable, ModelLifecycleState::kShutdown));
}

TEST(ModelState, IllegalTransitions) {
    EXPECT_FALSE(IsLegalModelLifecycleTransition(
        ModelLifecycleState::kUninitialized, ModelLifecycleState::kShutdown));
    EXPECT_FALSE(IsLegalModelLifecycleTransition(
        ModelLifecycleState::kReady, ModelLifecycleState::kUninitialized));
    EXPECT_FALSE(IsLegalModelLifecycleTransition(
        ModelLifecycleState::kReady, ModelLifecycleState::kUnavailable));
    EXPECT_FALSE(IsLegalModelLifecycleTransition(
        ModelLifecycleState::kUnavailable, ModelLifecycleState::kReady));
    EXPECT_FALSE(IsLegalModelLifecycleTransition(
        ModelLifecycleState::kShutdown, ModelLifecycleState::kReady));
    EXPECT_FALSE(IsLegalModelLifecycleTransition(
        ModelLifecycleState::kShutdown, ModelLifecycleState::kUninitialized));
}

TEST(ModelState, ValidateAcceptsLegalTransition) {
    const ak::TransitionResult result = ValidateModelLifecycleTransition(
        ModelLifecycleState::kUninitialized, ModelLifecycleState::kReady);
    EXPECT_TRUE(result.Accepted());
    EXPECT_FALSE(result.Rejected());
}

TEST(ModelState, ValidateRejectsIllegalTransition) {
    const ak::TransitionResult result = ValidateModelLifecycleTransition(
        ModelLifecycleState::kShutdown, ModelLifecycleState::kReady);
    EXPECT_TRUE(result.Rejected());
    EXPECT_FALSE(result.Accepted());
}

}  // namespace
}  // namespace ak::model
