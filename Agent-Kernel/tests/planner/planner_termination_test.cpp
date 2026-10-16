// ============================================================
// planner_termination_test.cpp - P1-IS005 termination protocol
// ============================================================
// PLN-059/060/061/063/020/018: drain-before-terminate, mandatory
// shutdown without Agent acknowledgement, termination creates no
// result, post-Terminated service unavailability (including
// PlannerInspectionService - MIN-001), root accessors remain
// callable, delivered values remain readable.
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

TEST(PlannerTermination, AcceptedRequestCompletesBeforeTermination) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());
    const auto completion = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    EXPECT_EQ(planner.OpenExchangeCount(), 0);

    // Termination creates no planning result: the already
    // delivered result count is unchanged and no new result is
    // produced by the Terminate call.
    const PlanningResult delivered = completion.result;
    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Terminate().IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kTerminated);
    EXPECT_EQ(delivered.result_id, completion.result.result_id);
}

TEST(PlannerTermination, OpenExchangesBlockTerminationUntilDrained) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());

    const auto blocked = planner.LifecycleContract().Lifecycle().Terminate();
    EXPECT_EQ(blocked.status, PlannerLifecycleResultStatus::kBusy);
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kPlanning);
    EXPECT_EQ(planner.OpenExchangeCount(), 1);

    const auto completion = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    EXPECT_TRUE(planner.LifecycleContract().Lifecycle().Terminate().IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kTerminated);
}

// Negative API surface: no Agent acknowledgement API exists on
// the Planner boundary (Agent acknowledgement never gates
// termination).
template <typename T, typename = void>
struct HasAcknowledgeTermination : std::false_type {};
template <typename T>
struct HasAcknowledgeTermination<
    T, std::void_t<decltype(std::declval<T&>().AcknowledgeTermination())>>
    : std::true_type {};

TEST(PlannerTermination, MandatoryShutdownCompletesWithoutAgentAcknowledgement) {
    static_assert(!HasAcknowledgeTermination<Planner>::value);
    static_assert(!HasAcknowledgeTermination<LifecycleParticipationService>::value);

    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    // Terminate() completes Terminating -> Terminated internally.
    EXPECT_TRUE(planner.LifecycleContract().Lifecycle().Terminate().IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kTerminated);
}

TEST(PlannerTermination, PostTerminatedPlannerServicesAreUnavailable) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();
    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Terminate().IsAccepted());

    // Planning service.
    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    EXPECT_EQ(acceptance.status, PlanningAcceptanceStatus::kUnavailable);
    const auto completion = planner.AgentContract().Planning().CompletePlanningExchange(
        MakePlanningRequestId(1));
    EXPECT_EQ(completion.status, PlanningCompletionStatus::kRejectedTerminated);

    // Lifecycle participation service.
    EXPECT_EQ(planner.LifecycleContract().Lifecycle().Initialize().status,
              PlannerLifecycleResultStatus::kUnavailable);
    EXPECT_EQ(planner.LifecycleContract().Lifecycle().Activate().status,
              PlannerLifecycleResultStatus::kUnavailable);
    EXPECT_EQ(planner.LifecycleContract().Lifecycle().Suspend().status,
              PlannerLifecycleResultStatus::kUnavailable);
    EXPECT_EQ(planner.LifecycleContract().Lifecycle().Resume().status,
              PlannerLifecycleResultStatus::kUnavailable);
    EXPECT_EQ(planner.LifecycleContract().Lifecycle().Terminate().status,
              PlannerLifecycleResultStatus::kUnavailable);

    // Inspection service (MIN-001): unavailable after Terminated.
    const auto inspection = planner.Inspection().GetOperationalState();
    EXPECT_EQ(inspection.status, PlannerInspectionStatus::kUnavailable);
    EXPECT_FALSE(inspection.IsAvailable());
    EXPECT_EQ(inspection.operational, PlannerOperationalState::kTerminated);

    // Planner root accessors remain callable as the ONLY
    // post-terminated observation path.
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kTerminated);
    EXPECT_EQ(planner.GetOperationalState(), PlannerOperationalState::kTerminated);
    EXPECT_EQ(planner.OpenExchangeCount(), 0);
    const PlannerState state = planner.GetState();
    EXPECT_EQ(state.session_count, 0);
    EXPECT_EQ(state.active_artifact_count, 0);
}

TEST(PlannerTermination, DeliveredValuesRemainReadableAfterTermination) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance = planner.AgentContract().Planning().Submit(
        fx.MakeRequest(1, "survives"));
    ASSERT_TRUE(acceptance.IsAccepted());
    const auto completion = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    const PlanningResult delivered = completion.result;

    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Terminate().IsAccepted());

    // Already-delivered immutable Agent-owned values remain
    // readable; they are no longer Planner services or
    // Planner-owned objects.
    EXPECT_TRUE(delivered.IsValid());
    EXPECT_TRUE(delivered.IsSuccess());
    EXPECT_EQ(delivered.artifact_view.payload, "survives");
    EXPECT_TRUE(delivered.artifact_view.artifact_id.IsValid());
    EXPECT_EQ(delivered.artifact_view.execution_plan.steps.front(), "survives");
}

TEST(PlannerTermination, InspectionAvailableInEveryNonTerminatedState) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();

    auto expect_available = [&](PlannerOperationalState expected) {
        const auto inspection = planner.Inspection().GetOperationalState();
        EXPECT_EQ(inspection.status, PlannerInspectionStatus::kAvailable);
        EXPECT_TRUE(inspection.IsAvailable());
        EXPECT_EQ(inspection.operational, expected);
    };

    expect_available(PlannerOperationalState::kCreated);
    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Initialize().IsAccepted());
    expect_available(PlannerOperationalState::kInitializing);
    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Activate().IsAccepted());
    expect_available(PlannerOperationalState::kReady);

    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());
    expect_available(PlannerOperationalState::kPlanning);

    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Suspend().IsAccepted());
    expect_available(PlannerOperationalState::kSuspended);

    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Resume().IsAccepted());
    const auto completion = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    expect_available(PlannerOperationalState::kReady);

    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Terminate().IsAccepted());
    EXPECT_EQ(planner.Inspection().GetOperationalState().status,
              PlannerInspectionStatus::kUnavailable);
    EXPECT_EQ(planner.Inspection().GetOperationalState().operational,
              PlannerOperationalState::kTerminated);
}

}  // namespace
}  // namespace ak::planner
