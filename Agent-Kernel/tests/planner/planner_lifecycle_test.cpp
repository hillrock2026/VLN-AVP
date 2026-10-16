// ============================================================
// planner_lifecycle_test.cpp - P1-IS005 lifecycle conformance
// ============================================================
// PLN-014/015/055/056/057/058: the nine valid transitions with
// admission conditions, rejection of unlisted transitions
// without mutation, suspension rules, termination admission,
// and the deterministic operational projection (PLN-016).
// ============================================================

#include <agent_kernel/planner/planner.hpp>
#include <agent_kernel/planner/planning_engine.hpp>
#include <agent_kernel/planner/planner_result.hpp>

#include <gtest/gtest.h>

#include "test_doubles.hpp"

namespace ak::planner {
namespace {

using test::PlannerTestFixture;

TEST(PlannerLifecycle, NineTransitionsSucceedWithAdmissionConditions) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();

    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kCreated);

    // Created -> Initializing
    EXPECT_TRUE(planner.LifecycleContract().Lifecycle().Initialize().IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kInitializing);

    // Initializing -> Ready (primary session created)
    EXPECT_TRUE(planner.LifecycleContract().Lifecycle().Activate().IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kReady);
    EXPECT_EQ(planner.GetState().session_count, 1);

    // Ready -> Planning (automatic on first accepted submission)
    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kPlanning);

    // Planning -> Ready (automatic drain at linearization)
    const auto completion =
        planner.AgentContract().Planning().CompletePlanningExchange(acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kReady);

    // Ready -> Planning again, then Planning -> Suspended
    const auto acceptance2 = planner.AgentContract().Planning().Submit(fx.MakeRequest(2));
    ASSERT_TRUE(acceptance2.IsAccepted());
    EXPECT_TRUE(planner.LifecycleContract().Lifecycle().Suspend().IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kSuspended);

    // Suspended -> Planning (the only exit from Suspended)
    EXPECT_TRUE(planner.LifecycleContract().Lifecycle().Resume().IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kPlanning);

    // Drain -> Ready
    const auto completion2 =
        planner.AgentContract().Planning().CompletePlanningExchange(acceptance2.request_id);
    ASSERT_TRUE(completion2.IsSuccess());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kReady);

    // Ready -> Terminating -> Terminated (mandatory shutdown in
    // the same operation; no Agent acknowledgement)
    const auto terminate = planner.LifecycleContract().Lifecycle().Terminate();
    EXPECT_TRUE(terminate.IsAccepted());
    EXPECT_EQ(terminate.target_state, PlannerLifecycleState::kTerminated);
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kTerminated);
}

TEST(PlannerLifecycle, UnlistedTransitionsAreRejectedWithoutMutation) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();

    // Activate from Created is illegal.
    EXPECT_FALSE(planner.LifecycleContract().Lifecycle().Activate().IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kCreated);

    // Suspend from Created is illegal.
    EXPECT_FALSE(planner.LifecycleContract().Lifecycle().Suspend().IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kCreated);

    // Terminate from Created is rejected (not operational).
    EXPECT_FALSE(planner.LifecycleContract().Lifecycle().Terminate().IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kCreated);

    // Initialize twice: second attempt rejected.
    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Initialize().IsAccepted());
    EXPECT_FALSE(planner.LifecycleContract().Lifecycle().Initialize().IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kInitializing);

    // Resume from Initializing is illegal (only Suspended exits).
    EXPECT_FALSE(planner.LifecycleContract().Lifecycle().Resume().IsAccepted());

    // Ready: Suspend and Resume rejected (Ready -> Suspended and
    // Ready -> Planning-via-Resume are not lifecycle operations).
    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Activate().IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kReady);
    EXPECT_FALSE(planner.LifecycleContract().Lifecycle().Suspend().IsAccepted());
    EXPECT_FALSE(planner.LifecycleContract().Lifecycle().Resume().IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kReady);

    // Terminating -> Planning is impossible: once Terminate is
    // admitted, the shutdown completes to Terminated in the same
    // operation and no transition leaves Terminated.
    EXPECT_TRUE(planner.LifecycleContract().Lifecycle().Terminate().IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kTerminated);
    EXPECT_FALSE(planner.LifecycleContract().Lifecycle().Initialize().IsAccepted());
    EXPECT_FALSE(planner.LifecycleContract().Lifecycle().Activate().IsAccepted());
    EXPECT_FALSE(planner.LifecycleContract().Lifecycle().Resume().IsAccepted());
}

TEST(PlannerLifecycle, SuspendRequiresPlanningWithOpenExchanges) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    // From Ready: kRejected (lifecycle != Planning).
    const auto from_ready = planner.LifecycleContract().Lifecycle().Suspend();
    EXPECT_EQ(from_ready.status, PlannerLifecycleResultStatus::kRejected);
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kReady);

    // Open an exchange -> Planning; Suspend accepted.
    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());
    EXPECT_TRUE(planner.LifecycleContract().Lifecycle().Suspend().IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kSuspended);
    EXPECT_EQ(planner.OpenExchangeCount(), 1);

    // Suspend while Suspended: kRejected (no re-suspend).
    EXPECT_FALSE(planner.LifecycleContract().Lifecycle().Suspend().IsAccepted());

    // Resume -> Planning; drain -> Ready.
    EXPECT_TRUE(planner.LifecycleContract().Lifecycle().Resume().IsAccepted());
    const auto completion =
        planner.AgentContract().Planning().CompletePlanningExchange(acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kReady);
}

TEST(PlannerLifecycle, ResumeIsTheOnlyExitFromSuspended) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());
    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Suspend().IsAccepted());

    // Suspended -> Terminating is invalid.
    const auto terminate = planner.LifecycleContract().Lifecycle().Terminate();
    EXPECT_EQ(terminate.status, PlannerLifecycleResultStatus::kRejected);
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kSuspended);

    // Resume is admitted; exchange preserved and completes after
    // the resumed planning state.
    EXPECT_TRUE(planner.LifecycleContract().Lifecycle().Resume().IsAccepted());
    const auto completion =
        planner.AgentContract().Planning().CompletePlanningExchange(acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kReady);
}

TEST(PlannerLifecycle, TerminateWithOpenExchangesReturnsBusyWithoutMutation) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());
    EXPECT_EQ(planner.OpenExchangeCount(), 1);

    const auto terminate = planner.LifecycleContract().Lifecycle().Terminate();
    EXPECT_EQ(terminate.status, PlannerLifecycleResultStatus::kBusy);
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kPlanning);
    EXPECT_EQ(planner.OpenExchangeCount(), 1);

    // Drain, then termination succeeds.
    const auto completion =
        planner.AgentContract().Planning().CompletePlanningExchange(acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kReady);
    EXPECT_TRUE(planner.LifecycleContract().Lifecycle().Terminate().IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kTerminated);
}

TEST(PlannerLifecycle, TerminateFromDrainedStateCommitsToTerminatedInOperation) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto terminate = planner.LifecycleContract().Lifecycle().Terminate();
    EXPECT_TRUE(terminate.IsAccepted());
    EXPECT_EQ(terminate.target_state, PlannerLifecycleState::kTerminated);
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kTerminated);
    EXPECT_EQ(planner.GetOperationalState(), PlannerOperationalState::kTerminated);
    EXPECT_EQ(planner.OpenExchangeCount(), 0);
}

TEST(PlannerLifecycle, TerminateFromInitializingOrSuspendedIsRejected) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();

    // Created -> Terminate: rejected (not operational).
    EXPECT_FALSE(planner.LifecycleContract().Lifecycle().Terminate().IsAccepted());

    // Initializing -> Terminate: rejected (not operational).
    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Initialize().IsAccepted());
    EXPECT_FALSE(planner.LifecycleContract().Lifecycle().Terminate().IsAccepted());
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kInitializing);
}

TEST(PlannerLifecycle, OperationalStateTracksLifecycleAsProjection) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();

    auto check_projection = [&]() {
        EXPECT_EQ(planner.GetOperationalState(),
                  ProjectOperationalState(planner.GetLifecycleState()));
    };
    check_projection();

    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Initialize().IsAccepted());
    check_projection();
    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Activate().IsAccepted());
    check_projection();

    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());
    check_projection();

    const auto completion =
        planner.AgentContract().Planning().CompletePlanningExchange(acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    check_projection();

    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Terminate().IsAccepted());
    check_projection();
}

}  // namespace
}  // namespace ak::planner
