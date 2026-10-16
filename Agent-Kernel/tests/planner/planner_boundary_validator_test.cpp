// ============================================================
// planner_boundary_validator_test.cpp - P1-IS005 boundary
// validator
// ============================================================
// Executable representation-level validation: identity validity,
// operational projection consistency, session/artifact
// retirement at Terminated, inspection unavailability after
// Terminated (MIN-001), and extension isolation.
// ============================================================

#include <agent_kernel/foundation/kernel_diagnostics.hpp>
#include <agent_kernel/planner/planner.hpp>
#include <agent_kernel/planner/planner_boundary_validator.hpp>
#include <agent_kernel/planner/planning_engine.hpp>

#include <gtest/gtest.h>

#include "test_doubles.hpp"

namespace ak::planner {
namespace {

using test::PlannerTestFixture;

TEST(PlannerBoundaryValidator, ValidPlannerLifecycleProducesNoErrors) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();

    fx.ActivatePlanner();
    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());
    const auto completion = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Terminate().IsAccepted());

    ak::DiagnosticSink sink;
    PlannerBoundaryValidator validator;
    validator.Validate(planner, sink);
    EXPECT_FALSE(sink.HasErrors());
}

TEST(PlannerBoundaryValidator, InvalidIdentityIsReported) {
    ImmediatePlanningEngine engine;
    Planner planner(PlannerIdentity{}, engine);

    ak::DiagnosticSink sink;
    PlannerBoundaryValidator validator;
    validator.Validate(planner, sink);
    EXPECT_TRUE(sink.HasErrors());
}

TEST(PlannerBoundaryValidator, TerminatedStateInvariantsHold) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    fx.ActivatePlanner();
    const auto acceptance = fx.planner().AgentContract().Planning().Submit(
        fx.MakeRequest(1, "validated"));
    ASSERT_TRUE(acceptance.IsAccepted());
    const auto completion = fx.planner().AgentContract().Planning().
        CompletePlanningExchange(acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    ASSERT_TRUE(fx.planner().LifecycleContract().Lifecycle().Terminate().IsAccepted());

    ak::DiagnosticSink sink;
    PlannerBoundaryValidator validator;
    validator.Validate(fx.planner(), sink);

    bool saw_inspection_error = false;
    for (const auto& diagnostic : sink.All()) {
        if (diagnostic.code == 74) {
            saw_inspection_error = true;
        }
    }
    EXPECT_FALSE(saw_inspection_error);
    EXPECT_FALSE(sink.HasErrors());
}

}  // namespace
}  // namespace ak::planner
