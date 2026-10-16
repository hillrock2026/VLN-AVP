// ============================================================
// planner_artifact_test.cpp - P1-IS005 artifact ownership and
// replanning
// ============================================================
// PLN-023/024/025/026/027: PlanningArtifact and ExecutionPlan
// remain Planner-owned; delivered views are immutable Agent-owned
// value snapshots; replanning retires the superseded artifact
// atomically; retirement is irreversible.
// ============================================================

#include <agent_kernel/planner/planner.hpp>
#include <agent_kernel/planner/planning_engine.hpp>

#include <gtest/gtest.h>

#include <type_traits>
#include <utility>

#include "test_doubles.hpp"

namespace ak::planner {
namespace {

using test::PlannerTestFixture;
using test::FailingPlanningEngine;

TEST(PlannerArtifact, SuccessfulCompletionCreatesOneArtifactAndPlan) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance = planner.AgentContract().Planning().Submit(
        fx.MakeRequest(1, "goal-artifact"));
    ASSERT_TRUE(acceptance.IsAccepted());
    const auto completion = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    ASSERT_TRUE(completion.result.IsSuccess());

    EXPECT_TRUE(completion.result.artifact_view.artifact_id.IsValid());
    EXPECT_EQ(completion.result.artifact_view.session_id, fx.PrimarySessionId());
    EXPECT_TRUE(completion.result.artifact_view.execution_plan.execution_plan_id.IsValid());
    EXPECT_EQ(completion.result.artifact_view.payload, "goal-artifact");
    EXPECT_EQ(planner.GetState().active_artifact_count, 1);
}

TEST(PlannerArtifact, FailedCompletionProducesNoArtifact) {
    FailingPlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());
    const auto completion = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    EXPECT_EQ(completion.result.status, PlanningResultStatus::kFailed);
    EXPECT_FALSE(completion.result.artifact_view.artifact_id.IsValid());
    EXPECT_EQ(planner.GetState().active_artifact_count, 0);
}

TEST(PlannerArtifact, AgentOwnedViewIsAnIndependentValue) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance = planner.AgentContract().Planning().Submit(
        fx.MakeRequest(1, "original-goal"));
    ASSERT_TRUE(acceptance.IsAccepted());
    const auto completion = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());

    // Mutating the delivered view does not affect Planner state.
    PlanningArtifactView view = completion.result.artifact_view;
    view.payload = "mutated";
    view.metadata.version = 99;
    EXPECT_EQ(planner.GetState().active_artifact_count, 1);

    // A second exchange proves the original snapshot is unchanged.
    const auto acceptance2 = planner.AgentContract().Planning().Submit(
        fx.MakeRequest(2, "second-goal"));
    ASSERT_TRUE(acceptance2.IsAccepted());
    const auto completion2 = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance2.request_id);
    ASSERT_TRUE(completion2.IsSuccess());
    EXPECT_EQ(completion2.result.artifact_view.payload, "second-goal");
    EXPECT_EQ(view.payload, "mutated");  // Agent-owned copy
    EXPECT_EQ(completion.result.artifact_view.payload, "original-goal");  // delivered copy
}

TEST(PlannerArtifact, ReplanningRetiresPreviousArtifactAtomically) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance1 = planner.AgentContract().Planning().Submit(
        fx.MakeRequest(1, "plan-1"));
    ASSERT_TRUE(acceptance1.IsAccepted());
    const auto completion1 = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance1.request_id);
    ASSERT_TRUE(completion1.IsSuccess());
    const PlanningArtifactView view1 = completion1.result.artifact_view;
    EXPECT_EQ(planner.GetState().active_artifact_count, 1);

    // Replanning: a new exchange produces a new artifact and
    // atomically retires the superseded one.
    const auto acceptance2 = planner.AgentContract().Planning().Submit(
        fx.MakeRequest(2, "plan-2"));
    ASSERT_TRUE(acceptance2.IsAccepted());
    const auto completion2 = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance2.request_id);
    ASSERT_TRUE(completion2.IsSuccess());
    EXPECT_NE(completion2.result.artifact_view.artifact_id, view1.artifact_id);
    EXPECT_EQ(planner.GetState().active_artifact_count, 1);

    // The previously delivered view remains readable and unchanged.
    EXPECT_EQ(view1.payload, "plan-1");
    EXPECT_TRUE(view1.artifact_id.IsValid());
}

TEST(PlannerArtifact, ArtifactLifetimeEndsAtPlannerTermination) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance = planner.AgentContract().Planning().Submit(
        fx.MakeRequest(1, "terminal-goal"));
    ASSERT_TRUE(acceptance.IsAccepted());
    const auto completion = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    const PlanningArtifactView view = completion.result.artifact_view;
    const ExecutionPlanSnapshot plan = completion.result.artifact_view.execution_plan;
    EXPECT_EQ(planner.GetState().active_artifact_count, 1);

    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Terminate().IsAccepted());
    const PlannerState state = planner.GetState();
    EXPECT_EQ(state.active_artifact_count, 0);
    EXPECT_EQ(state.session_count, 0);

    // Delivered Agent-owned values remain readable after
    // termination (AK0044 Revision A Section 10.3).
    EXPECT_EQ(view.payload, "terminal-goal");
    EXPECT_TRUE(view.artifact_id.IsValid());
    EXPECT_EQ(view.execution_plan, plan);
}

// Negative API surface: retired artifacts are never resurrected
// and the Agent never obtains renewed access; no lookup/
// activation API exists on the public boundary.
template <typename T, typename = void>
struct HasResurrectArtifact : std::false_type {};
template <typename T>
struct HasResurrectArtifact<
    T, std::void_t<decltype(std::declval<T&>().ResurrectArtifact(
           std::declval<const PlanningArtifactId&>()))>> : std::true_type {};

TEST(PlannerArtifact, NoResurrectionApiExists) {
    static_assert(!HasResurrectArtifact<Planner>::value);
    static_assert(!HasResurrectArtifact<PlanningService>::value);
    static_assert(!HasResurrectArtifact<PlannerAgentContract>::value);
}

}  // namespace
}  // namespace ak::planner
