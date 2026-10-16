// ============================================================
// agent_planner_host_test.cpp - P1-IS005 AgentPlannerHost
// ============================================================
// PLN-052/053/036: AgentPlannerHost is the single production
// composition root; it owns the default ImmediatePlanningEngine,
// the real Planner, and the real AgentPlannerBinding with the
// normative member order (engine_ -> planner_ -> binding_).
// ============================================================

#include <agent_kernel/agent_planner/agent_planner_host.hpp>

#include <gtest/gtest.h>

#include <type_traits>

namespace ak::agent {
namespace pl = ak::planner;

TEST(AgentPlannerHost, OwnsRealPlannerEngineAndBinding) {
    const pl::PlannerIdentity identity = pl::MakePlannerIdentity(100);
    AgentPlannerHost host(identity);

    EXPECT_EQ(host.GetPlannerIdentity(), identity);
    EXPECT_EQ(host.Planner().GetIdentity(), identity);

    // The binding views the planner's own contracts.
    EXPECT_EQ(&host.Binding().Capability(), &host.Planner().AgentContract());
    EXPECT_EQ(&host.Binding().Lifecycle(), &host.Planner().LifecycleContract());

    // Lifecycle starts at Created.
    EXPECT_EQ(host.Planner().GetLifecycleState(), pl::PlannerLifecycleState::kCreated);
}

TEST(AgentPlannerHost, ProductionCompositionRoundTrip) {
    AgentPlannerHost host(pl::MakePlannerIdentity(101));
    auto& binding = host.Binding();

    EXPECT_TRUE(binding.Initialize().IsAccepted());
    EXPECT_TRUE(binding.Activate().IsAccepted());
    EXPECT_EQ(host.Planner().GetLifecycleState(), pl::PlannerLifecycleState::kReady);

    pl::PlanningRequest request;
    request.request_id = pl::MakePlanningRequestId(1);
    request.session_id = pl::MakePlannerSessionId(pl::kPrimaryPlannerSessionIdValue);
    request.goal = "host-goal";

    const auto acceptance = binding.Submit(request);
    ASSERT_TRUE(acceptance.IsAccepted());
    const auto completion = binding.CompletePlanningExchange(acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    EXPECT_EQ(completion.result.artifact_view.payload, "host-goal");
    EXPECT_EQ(host.Planner().GetLifecycleState(), pl::PlannerLifecycleState::kReady);
}

TEST(AgentPlannerHost, NonCopyable) {
    static_assert(!std::is_copy_constructible_v<AgentPlannerHost>);
    static_assert(!std::is_copy_assignable_v<AgentPlannerHost>);
    static_assert(!std::is_move_constructible_v<AgentPlannerHost>);
    static_assert(!std::is_move_assignable_v<AgentPlannerHost>);
}

TEST(AgentPlannerHost, HostOutlivesBindingUsage) {
    // The host SHALL be destroyed after the Agent stops invoking
    // the binding; within this test, all binding use completes
    // before the host goes out of scope at function exit.
    AgentPlannerHost host(pl::MakePlannerIdentity(102));
    auto& binding = host.Binding();
    ASSERT_TRUE(binding.Initialize().IsAccepted());
    ASSERT_TRUE(binding.Activate().IsAccepted());
    EXPECT_EQ(binding.GetOperationalState(), pl::PlannerOperationalState::kReady);
}

}  // namespace ak::agent
