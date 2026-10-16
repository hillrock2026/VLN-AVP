// ============================================================
// agent_planner_binding_test.cpp - P1-IS005 AgentPlannerBinding
// ============================================================
// PLN-050/051/018: the binding is the real Agent-owned invocation
// infrastructure; the post-Terminated refusal gate refuses
// without invoking any Planner Service; GetOperationalState reads
// the Planner root accessor directly (MIN-001).
// ============================================================

#include <agent_kernel/agent_planner/agent_planner_host.hpp>

#include <gtest/gtest.h>

namespace ak::agent {
namespace pl = ak::planner;

TEST(AgentPlannerBinding, DelegatesToRealPlannerServices) {
    AgentPlannerHost host(pl::MakePlannerIdentity(200));
    auto& binding = host.Binding();

    ASSERT_TRUE(binding.Initialize().IsAccepted());
    ASSERT_TRUE(binding.Activate().IsAccepted());
    EXPECT_EQ(binding.GetOperationalState(), pl::PlannerOperationalState::kReady);

    pl::PlanningRequest request;
    request.request_id = pl::MakePlanningRequestId(1);
    request.session_id = pl::MakePlannerSessionId(pl::kPrimaryPlannerSessionIdValue);
    request.goal = "binding-goal";

    const auto acceptance = binding.Submit(request);
    ASSERT_TRUE(acceptance.IsAccepted());
    const auto completion = binding.CompletePlanningExchange(request.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    ASSERT_TRUE(completion.HasResult());

    // The result is produced by the REAL Planner service: valid
    // Planner-assigned result id and one-to-one request
    // correlation.
    EXPECT_TRUE(completion.result.result_id.IsValid());
    EXPECT_EQ(completion.result.request_id, request.request_id);
    EXPECT_EQ(completion.result.artifact_view.payload, "binding-goal");
    EXPECT_EQ(binding.GetOperationalState(), pl::PlannerOperationalState::kReady);
}

TEST(AgentPlannerBinding, PostTerminatedRefusalGateRefusesWithoutServiceCall) {
    AgentPlannerHost host(pl::MakePlannerIdentity(201));
    auto& binding = host.Binding();

    ASSERT_TRUE(binding.Initialize().IsAccepted());
    ASSERT_TRUE(binding.Activate().IsAccepted());
    ASSERT_TRUE(binding.Terminate().IsAccepted());
    EXPECT_EQ(host.Planner().GetLifecycleState(), pl::PlannerLifecycleState::kTerminated);

    pl::PlanningRequest request;
    request.request_id = pl::MakePlanningRequestId(1);
    request.session_id = pl::MakePlannerSessionId(pl::kPrimaryPlannerSessionIdValue);
    request.goal = "post-terminated";

    const auto acceptance = binding.Submit(request);
    EXPECT_EQ(acceptance.status, pl::PlanningAcceptanceStatus::kUnavailable);
    EXPECT_STREQ(acceptance.message, "planner terminated");

    const auto completion = binding.CompletePlanningExchange(request.request_id);
    EXPECT_EQ(completion.status, pl::PlanningCompletionStatus::kRejectedTerminated);

    EXPECT_EQ(binding.Initialize().status, pl::PlannerLifecycleResultStatus::kUnavailable);
    EXPECT_EQ(binding.Activate().status, pl::PlannerLifecycleResultStatus::kUnavailable);
    EXPECT_EQ(binding.Suspend().status, pl::PlannerLifecycleResultStatus::kUnavailable);
    EXPECT_EQ(binding.Resume().status, pl::PlannerLifecycleResultStatus::kUnavailable);
    EXPECT_EQ(binding.Terminate().status, pl::PlannerLifecycleResultStatus::kUnavailable);

    // The gate read only the Planner root state: no Planner
    // service was invoked, no exchange was opened, no state
    // mutated.
    EXPECT_EQ(host.Planner().OpenExchangeCount(), 0);
    EXPECT_EQ(host.Planner().GetState().session_count, 0);

    // GetOperationalState reads the root accessor directly and
    // remains usable after termination without invoking any
    // Planner Service (MIN-001).
    EXPECT_EQ(binding.GetOperationalState(), pl::PlannerOperationalState::kTerminated);
}

TEST(AgentPlannerBinding, GetOperationalStateReadsRootAccessorDirectly) {
    AgentPlannerHost host(pl::MakePlannerIdentity(202));
    auto& binding = host.Binding();

    EXPECT_EQ(binding.GetOperationalState(), pl::PlannerOperationalState::kCreated);
    ASSERT_TRUE(binding.Initialize().IsAccepted());
    EXPECT_EQ(binding.GetOperationalState(), pl::PlannerOperationalState::kInitializing);
    ASSERT_TRUE(binding.Activate().IsAccepted());
    EXPECT_EQ(binding.GetOperationalState(), pl::PlannerOperationalState::kReady);

    pl::PlanningRequest request;
    request.request_id = pl::MakePlanningRequestId(1);
    request.session_id = pl::MakePlannerSessionId(pl::kPrimaryPlannerSessionIdValue);
    request.goal = "state-goal";
    ASSERT_TRUE(binding.Submit(request).IsAccepted());
    EXPECT_EQ(binding.GetOperationalState(), pl::PlannerOperationalState::kPlanning);
}

}  // namespace ak::agent
