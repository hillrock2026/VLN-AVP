// ============================================================
// planner_exchange_test.cpp - P1-IS005 planning exchange
// ============================================================
// PLN-028/029/030/031/032/033: submission and acceptance
// semantics, value-copy ownership, refusal without obligation,
// open-exchange accounting, and one-to-one request->result
// correlation.
// ============================================================

#include <agent_kernel/planner/planner.hpp>
#include <agent_kernel/planner/planning_engine.hpp>

#include <gtest/gtest.h>

#include "test_doubles.hpp"

namespace ak::planner {
namespace {

using test::PlannerTestFixture;

TEST(PlannerExchange, ValidSubmissionOpensExchangeAndTransitionsToPlanning) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kReady);

    PlanningRequest request = fx.MakeRequest(1, "goal-1");
    const auto acceptance = planner.AgentContract().Planning().Submit(request);
    ASSERT_TRUE(acceptance.IsAccepted());
    EXPECT_EQ(acceptance.request_id, request.request_id);
    EXPECT_EQ(planner.OpenExchangeCount(), 1);
    EXPECT_EQ(planner.GetState().open_exchange_count, 1);
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kPlanning);

    // Value-copy semantics: mutating the Agent-owned request after
    // submission does not affect the Planner-owned exchange.
    request.goal = "mutated-after-submission";
    const auto completion =
        planner.AgentContract().Planning().CompletePlanningExchange(acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    EXPECT_EQ(completion.result.artifact_view.payload, "goal-1");
    ASSERT_FALSE(completion.result.artifact_view.execution_plan.steps.empty());
    EXPECT_EQ(completion.result.artifact_view.execution_plan.steps.front(), "goal-1");
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kReady);
}

TEST(PlannerExchange, InvalidRequestsAreRefusedWithoutObligation) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    // Invalid request id (default = 0).
    PlanningRequest invalid_id = fx.MakeRequest(1);
    invalid_id.request_id = PlanningRequestId{};
    EXPECT_EQ(planner.AgentContract().Planning().Submit(invalid_id).status,
              PlanningAcceptanceStatus::kRefused);

    // Invalid session id.
    PlanningRequest wrong_session = fx.MakeRequest(2);
    wrong_session.session_id = MakePlannerSessionId(999);
    EXPECT_EQ(planner.AgentContract().Planning().Submit(wrong_session).status,
              PlanningAcceptanceStatus::kRefused);

    // Empty goal.
    PlanningRequest empty_goal = fx.MakeRequest(3, "");
    EXPECT_EQ(planner.AgentContract().Planning().Submit(empty_goal).status,
              PlanningAcceptanceStatus::kRefused);

    // No exchange was opened; no result obligation exists.
    EXPECT_EQ(planner.OpenExchangeCount(), 0);
    EXPECT_EQ(planner.GetState().open_exchange_count, 0);
}

TEST(PlannerExchange, DuplicateActiveRequestIdIsRefused) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());

    const auto duplicate = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    EXPECT_EQ(duplicate.status, PlanningAcceptanceStatus::kRefused);
    EXPECT_EQ(planner.OpenExchangeCount(), 1);
}

TEST(PlannerExchange, RetiredRequestIdIsRefused) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());
    const auto completion =
        planner.AgentContract().Planning().CompletePlanningExchange(acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());

    // Identity reuse after retirement is prohibited (one-to-one
    // request -> result correlation is preserved).
    const auto reuse = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    EXPECT_EQ(reuse.status, PlanningAcceptanceStatus::kRefused);
    EXPECT_EQ(planner.OpenExchangeCount(), 0);
}

TEST(PlannerExchange, SubmitWhileTerminatingOrTerminatedIsUnavailable) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Terminate().IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kTerminated);

    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    EXPECT_EQ(acceptance.status, PlanningAcceptanceStatus::kUnavailable);
    EXPECT_EQ(planner.OpenExchangeCount(), 0);
}

TEST(PlannerExchange, UnknownRequestIdCompletionIsRejectedInvalid) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto completion = planner.AgentContract().Planning().CompletePlanningExchange(
        MakePlanningRequestId(999));
    EXPECT_EQ(completion.status, PlanningCompletionStatus::kRejectedInvalid);
    EXPECT_FALSE(completion.HasResult());
}

TEST(PlannerExchange, CompletionLinearizationProducesExactlyOneValidResult) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());

    const auto completion =
        planner.AgentContract().Planning().CompletePlanningExchange(acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    EXPECT_TRUE(completion.HasResult());
    EXPECT_TRUE(completion.result.result_id.IsValid());
    EXPECT_TRUE(completion.result.IsValid());
    EXPECT_EQ(planner.OpenExchangeCount(), 0);
    EXPECT_EQ(planner.GetState().open_exchange_count, 0);

    // Result and artifact view are plain values (no Planner or
    // Runtime references); the result is copyable.
    const PlanningResult copied = completion.result;
    EXPECT_TRUE(copied.IsValid());
    EXPECT_EQ(copied.artifact_view.artifact_id,
              completion.result.artifact_view.artifact_id);
}

TEST(PlannerExchange, ResultCorrelationIsOneToOne) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance =
        planner.AgentContract().Planning().Submit(fx.MakeRequest(7, "correlate-me"));
    ASSERT_TRUE(acceptance.IsAccepted());

    const auto completion =
        planner.AgentContract().Planning().CompletePlanningExchange(acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    EXPECT_EQ(completion.result.request_id, MakePlanningRequestId(7));
    EXPECT_EQ(completion.result.session_id, fx.PrimarySessionId());
}

}  // namespace
}  // namespace ak::planner
