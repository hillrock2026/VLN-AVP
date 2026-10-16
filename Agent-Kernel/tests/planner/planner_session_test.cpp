// ============================================================
// planner_session_test.cpp - P1-IS005 session conformance
// ============================================================
// PLN-021/022/033: one primary Planner Session per Planner,
// created at Activate and retired at Terminated; session
// identity distinct from every other domain; deterministic open
// exchange accounting.
// ============================================================

#include <agent_kernel/planner/planner.hpp>
#include <agent_kernel/planner/planning_engine.hpp>

#include <gtest/gtest.h>

#include "test_doubles.hpp"

namespace ak::planner {
namespace {

using test::PlannerTestFixture;

TEST(PlannerSession, PrimarySessionCreatedAtActivateAndRetiredAtTerminated) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();

    EXPECT_EQ(planner.GetState().session_count, 0);
    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Initialize().IsAccepted());
    EXPECT_EQ(planner.GetState().session_count, 0);

    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Activate().IsAccepted());
    EXPECT_EQ(planner.GetState().session_count, 1);

    // Submissions are associated with the primary session.
    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());
    EXPECT_EQ(acceptance.session_id, fx.PrimarySessionId());

    // Drain and terminate; the primary session is retired.
    const auto completion =
        planner.AgentContract().Planning().CompletePlanningExchange(acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Terminate().IsAccepted());
    EXPECT_EQ(planner.GetState().session_count, 0);
    EXPECT_EQ(planner.GetState().open_exchange_count, 0);
}

TEST(PlannerSession, OpenExchangeAccountingIsDeterministic) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    EXPECT_EQ(planner.OpenExchangeCount(), 0);
    EXPECT_EQ(planner.GetState().open_exchange_count, 0);

    const auto first = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(first.IsAccepted());
    EXPECT_EQ(planner.OpenExchangeCount(), 1);

    const auto second = planner.AgentContract().Planning().Submit(fx.MakeRequest(2));
    ASSERT_TRUE(second.IsAccepted());
    EXPECT_EQ(planner.OpenExchangeCount(), 2);

    const auto completion =
        planner.AgentContract().Planning().CompletePlanningExchange(first.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    EXPECT_EQ(planner.OpenExchangeCount(), 1);
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kPlanning);

    const auto completion2 =
        planner.AgentContract().Planning().CompletePlanningExchange(second.request_id);
    ASSERT_TRUE(completion2.IsSuccess());
    EXPECT_EQ(planner.OpenExchangeCount(), 0);
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kReady);
}

TEST(PlannerSession, WrongSessionIdIsRefused) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    PlanningRequest request = fx.MakeRequest(1);
    request.session_id = MakePlannerSessionId(999);
    const auto acceptance = planner.AgentContract().Planning().Submit(request);
    EXPECT_EQ(acceptance.status, PlanningAcceptanceStatus::kRefused);
    EXPECT_EQ(planner.OpenExchangeCount(), 0);
}

}  // namespace
}  // namespace ak::planner
