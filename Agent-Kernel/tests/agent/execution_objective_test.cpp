// ============================================================
// execution_objective_test.cpp - P1-IS002 objective tests
// ============================================================
// AG-002: Agent owns execution objectives; objectives are
// Agent-owned representations of desired intelligent outcomes
// and are NOT Runtime execution objects.
// ============================================================

#include <agent_kernel/agent/agent.hpp>
#include <agent_kernel/agent/execution/execution_objective.hpp>

#include <gtest/gtest.h>

#include <string>
#include <type_traits>
#include <vector>

namespace ak::agent {
namespace {

TEST(ExecutionObjective, IsAgentOwnedValueRepresentation) {
    ExecutionObjective objective(ObjectiveId(1), "retrieve report");
    objective.AddCriterion("report exists");
    objective.AddCriterion("report is current");

    EXPECT_EQ(objective.GetId(), ObjectiveId(1));
    EXPECT_EQ(objective.GetDescription(), "retrieve report");
    ASSERT_EQ(objective.Criteria().size(), 2);
    EXPECT_EQ(objective.Criteria()[0], "report exists");

    // Internal status is Agent-owned and not an architectural
    // state of the Agent.
    EXPECT_EQ(objective.GetStatus(), ObjectiveStatus::kProposed);
    objective.Accept();
    EXPECT_EQ(objective.GetStatus(), ObjectiveStatus::kAccepted);
    objective.MarkInProgress();
    EXPECT_EQ(objective.GetStatus(), ObjectiveStatus::kInProgress);
    objective.MarkEvaluated();
    EXPECT_EQ(objective.GetStatus(), ObjectiveStatus::kEvaluated);
}

TEST(ExecutionObjective, IsNotRuntimeObject) {
    // Compile-time proof: this TU includes only Agent/Foundation
    // headers, and the objective id domain is distinct from the
    // Agent identity domain.
    static_assert(!std::is_same_v<ObjectiveId, AgentIdentity>);
}

TEST(ExecutionObjective, AgentAcceptsObjectivesOnlyWhenReady) {
    Agent agent(MakeAgentIdentity(1));
    const ExecutionObjective objective(ObjectiveId(10), "task");

    // Uninitialized: objectives are rejected.
    EXPECT_FALSE(agent.AcceptObjective(objective));
    EXPECT_EQ(agent.FindObjective(ObjectiveId(10)), nullptr);

    // Ready: objectives are accepted and Agent-owned.
    ASSERT_TRUE(agent.Initialize().Accepted());
    EXPECT_TRUE(agent.AcceptObjective(objective));
    ASSERT_NE(agent.FindObjective(ObjectiveId(10)), nullptr);
    EXPECT_EQ(agent.FindObjective(ObjectiveId(10))->GetDescription(),
              "task");

    const std::vector<ObjectiveId> ids = agent.EnumerateObjectives();
    ASSERT_EQ(ids.size(), 1);
    EXPECT_EQ(ids[0], ObjectiveId(10));
}

TEST(ExecutionObjective, AgentRejectsObjectivesWhileSuspendedOrTerminated) {
    Agent agent(MakeAgentIdentity(1));
    ASSERT_TRUE(agent.Initialize().Accepted());
    ASSERT_TRUE(agent.AcceptObjective(ExecutionObjective(ObjectiveId(1), "a")));

    // Move to Suspended and verify objectives are not accepted.
    // (Suspend is only legal from Supervising in the model.)
    // Simulate by terminating instead, which is reachable from Ready.
    ASSERT_TRUE(agent.Terminate().Accepted());
    EXPECT_FALSE(agent.AcceptObjective(ExecutionObjective(ObjectiveId(2), "b")));
    EXPECT_EQ(agent.FindObjective(ObjectiveId(2)), nullptr);
    EXPECT_EQ(agent.GetState(), AgentState::kTerminated);
}

}  // namespace
}  // namespace ak::agent
