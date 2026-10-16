// ============================================================
// planner_state_test.cpp - P1-IS005 lifecycle/operational state
// ============================================================
// PLN-013/014/015/016/017: the seven lifecycle states, the nine
// valid transitions, rejection of every unlisted transition,
// the typed 1:1 operational projection, and the read-only
// PlannerState summary.
// ============================================================

#include <agent_kernel/planner/planner_state.hpp>

#include <gtest/gtest.h>

#include <cstdint>

namespace ak::planner {
namespace {

TEST(PlannerState, LifecycleStateNamesAndCodes) {
    EXPECT_EQ(PlannerLifecycleStateName(PlannerLifecycleState::kCreated), "Created");
    EXPECT_EQ(PlannerLifecycleStateName(PlannerLifecycleState::kInitializing), "Initializing");
    EXPECT_EQ(PlannerLifecycleStateName(PlannerLifecycleState::kReady), "Ready");
    EXPECT_EQ(PlannerLifecycleStateName(PlannerLifecycleState::kPlanning), "Planning");
    EXPECT_EQ(PlannerLifecycleStateName(PlannerLifecycleState::kSuspended), "Suspended");
    EXPECT_EQ(PlannerLifecycleStateName(PlannerLifecycleState::kTerminating), "Terminating");
    EXPECT_EQ(PlannerLifecycleStateName(PlannerLifecycleState::kTerminated), "Terminated");
    EXPECT_EQ(PlannerLifecycleStateName(static_cast<PlannerLifecycleState>(99)), "Unknown");

    EXPECT_EQ(PlannerLifecycleStateCode(PlannerLifecycleState::kCreated), 0);
    EXPECT_EQ(PlannerLifecycleStateCode(PlannerLifecycleState::kTerminated), 6);
}

TEST(PlannerState, OperationalStateNames) {
    EXPECT_EQ(PlannerOperationalStateName(PlannerOperationalState::kCreated), "Created");
    EXPECT_EQ(PlannerOperationalStateName(PlannerOperationalState::kTerminated), "Terminated");
    EXPECT_EQ(PlannerOperationalStateName(static_cast<PlannerOperationalState>(99)), "Unknown");
}

TEST(PlannerState, NineValidTransitions) {
    EXPECT_TRUE(IsLegalPlannerLifecycleTransition(PlannerLifecycleState::kCreated,
                                                  PlannerLifecycleState::kInitializing));
    EXPECT_TRUE(IsLegalPlannerLifecycleTransition(PlannerLifecycleState::kInitializing,
                                                  PlannerLifecycleState::kReady));
    EXPECT_TRUE(IsLegalPlannerLifecycleTransition(PlannerLifecycleState::kReady,
                                                  PlannerLifecycleState::kPlanning));
    EXPECT_TRUE(IsLegalPlannerLifecycleTransition(PlannerLifecycleState::kPlanning,
                                                  PlannerLifecycleState::kReady));
    EXPECT_TRUE(IsLegalPlannerLifecycleTransition(PlannerLifecycleState::kPlanning,
                                                  PlannerLifecycleState::kSuspended));
    EXPECT_TRUE(IsLegalPlannerLifecycleTransition(PlannerLifecycleState::kSuspended,
                                                  PlannerLifecycleState::kPlanning));
    EXPECT_TRUE(IsLegalPlannerLifecycleTransition(PlannerLifecycleState::kReady,
                                                  PlannerLifecycleState::kTerminating));
    EXPECT_TRUE(IsLegalPlannerLifecycleTransition(PlannerLifecycleState::kPlanning,
                                                  PlannerLifecycleState::kTerminating));
    EXPECT_TRUE(IsLegalPlannerLifecycleTransition(PlannerLifecycleState::kTerminating,
                                                  PlannerLifecycleState::kTerminated));
}

TEST(PlannerState, ExhaustiveTransitionTable) {
    const auto states = {PlannerLifecycleState::kCreated,
                         PlannerLifecycleState::kInitializing,
                         PlannerLifecycleState::kReady,
                         PlannerLifecycleState::kPlanning,
                         PlannerLifecycleState::kSuspended,
                         PlannerLifecycleState::kTerminating,
                         PlannerLifecycleState::kTerminated};
    for (const auto from : states) {
        for (const auto to : states) {
            const bool expected = [&]() {
                switch (from) {
                    case PlannerLifecycleState::kCreated:
                        return to == PlannerLifecycleState::kInitializing;
                    case PlannerLifecycleState::kInitializing:
                        return to == PlannerLifecycleState::kReady;
                    case PlannerLifecycleState::kReady:
                        return to == PlannerLifecycleState::kPlanning ||
                               to == PlannerLifecycleState::kTerminating;
                    case PlannerLifecycleState::kPlanning:
                        return to == PlannerLifecycleState::kReady ||
                               to == PlannerLifecycleState::kSuspended ||
                               to == PlannerLifecycleState::kTerminating;
                    case PlannerLifecycleState::kSuspended:
                        return to == PlannerLifecycleState::kPlanning;
                    case PlannerLifecycleState::kTerminating:
                        return to == PlannerLifecycleState::kTerminated;
                    case PlannerLifecycleState::kTerminated:
                        return false;
                }
                return false;
            }();
            EXPECT_EQ(IsLegalPlannerLifecycleTransition(from, to), expected);
        }
    }
}

TEST(PlannerState, TransitionRuleAndValidatorAdapters) {
    EXPECT_TRUE(PlannerLifecycleTransitionRule(0, 1));   // Created -> Initializing
    EXPECT_TRUE(PlannerLifecycleTransitionRule(3, 4));   // Planning -> Suspended
    EXPECT_FALSE(PlannerLifecycleTransitionRule(3, 6));  // Planning -> Terminated
    EXPECT_FALSE(PlannerLifecycleTransitionRule(4, 5));  // Suspended -> Terminating

    EXPECT_TRUE(ValidatePlannerLifecycleTransition(PlannerLifecycleState::kCreated,
                                                   PlannerLifecycleState::kInitializing).Accepted());
    EXPECT_TRUE(ValidatePlannerLifecycleTransition(PlannerLifecycleState::kSuspended,
                                                   PlannerLifecycleState::kPlanning).Accepted());
    EXPECT_TRUE(ValidatePlannerLifecycleTransition(PlannerLifecycleState::kReady,
                                                   PlannerLifecycleState::kSuspended).Rejected());
    EXPECT_TRUE(ValidatePlannerLifecycleTransition(PlannerLifecycleState::kTerminating,
                                                   PlannerLifecycleState::kPlanning).Rejected());
}

TEST(PlannerState, OperationalStateIsDeterministicProjection) {
    EXPECT_EQ(ProjectOperationalState(PlannerLifecycleState::kCreated),
              PlannerOperationalState::kCreated);
    EXPECT_EQ(ProjectOperationalState(PlannerLifecycleState::kInitializing),
              PlannerOperationalState::kInitializing);
    EXPECT_EQ(ProjectOperationalState(PlannerLifecycleState::kReady),
              PlannerOperationalState::kReady);
    EXPECT_EQ(ProjectOperationalState(PlannerLifecycleState::kPlanning),
              PlannerOperationalState::kPlanning);
    EXPECT_EQ(ProjectOperationalState(PlannerLifecycleState::kSuspended),
              PlannerOperationalState::kSuspended);
    EXPECT_EQ(ProjectOperationalState(PlannerLifecycleState::kTerminating),
              PlannerOperationalState::kTerminating);
    EXPECT_EQ(ProjectOperationalState(PlannerLifecycleState::kTerminated),
              PlannerOperationalState::kTerminated);
}

TEST(PlannerState, ToLifecycleStateMapsToFoundationValue) {
    EXPECT_EQ(ToLifecycleState(PlannerLifecycleState::kCreated).Value(), 0);
    EXPECT_EQ(ToLifecycleState(PlannerLifecycleState::kReady).Value(), 2);
    EXPECT_EQ(ToLifecycleState(PlannerLifecycleState::kTerminated).Value(), 6);
}

TEST(PlannerState, StateSummaryEquality) {
    PlannerState a;
    PlannerState b;
    EXPECT_EQ(a, b);

    b.lifecycle = PlannerLifecycleState::kReady;
    EXPECT_NE(a, b);

    a.lifecycle = PlannerLifecycleState::kReady;
    a.operational = PlannerOperationalState::kReady;
    a.open_exchange_count = 2;
    a.active_artifact_count = 1;
    a.session_count = 1;

    const PlannerState c = a;
    EXPECT_EQ(a, c);
}

}  // namespace
}  // namespace ak::planner
