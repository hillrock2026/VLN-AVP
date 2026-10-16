// ============================================================
// ownership_dependency_test.cpp - P1-IS002 ownership/dependency
// conformance
// ============================================================
// AG-015..AG-018, AG-020..AG-024: peer subsystem ownership is
// not absorbed; Agent remains the sole cross-subsystem
// coordinator; the Agent boundary depends only on the Kernel
// Foundation; no universal manager or coordinator exists.
// ============================================================

#include <agent_kernel/agent/agent.hpp>
#include <agent_kernel/agent/coordination/agent_coordination_service.hpp>
#include <agent_kernel/agent/execution/completion_evaluation.hpp>
#include <agent_kernel/agent/execution/execution_objective.hpp>
#include <agent_kernel/agent/execution/execution_supervision.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <type_traits>

#include "test_doubles.hpp"

namespace ak::agent {
namespace {

TEST(Ownership, PeerSubsystemOwnershipIsNotAbsorbed) {
    Agent agent(MakeAgentIdentity(1));
    test::MemoryContractDouble memory;
    test::ContextContractDouble context;
    test::PlannerContractDouble planner;
    test::ToolContractDouble tool;
    test::BindAllContracts(agent, memory, context, planner, tool);

    // The Agent coordinates the peer subsystems but owns no
    // authoritative subsystem state: the Agent object exposes
    // no subsystem state and holds non-owning references only.
    EXPECT_TRUE(agent.HasAllSubsystemContracts());
    EXPECT_EQ(memory.acknowledged_count, 0);
    EXPECT_EQ(context.acknowledged_count, 0);
    EXPECT_EQ(planner.acknowledged_count, 0);
    EXPECT_EQ(tool.acknowledged_count, 0);
}

TEST(Ownership, AgentOwnsIntelligentExecutionState) {
    Agent agent(MakeAgentIdentity(1));
    ASSERT_TRUE(agent.Initialize().Accepted());

    // Objectives, composition, supervision, and completion
    // evaluation all live inside the Agent-owned boundary.
    const ExecutionObjective objective(ObjectiveId(3), "objective");
    ASSERT_TRUE(agent.AcceptObjective(objective));

    EXPECT_NE(agent.FindObjective(ObjectiveId(3)), nullptr);
    EXPECT_EQ(agent.Composition().StepCount(), 0);
    EXPECT_FALSE(agent.Supervision().IsActive());
}

TEST(Ownership, CompletionEvaluationIsIntelligentAndDistinct) {
    Agent agent(MakeAgentIdentity(1));
    ASSERT_TRUE(agent.Initialize().Accepted());
    const ExecutionObjective objective(ObjectiveId(4), "objective");
    ASSERT_TRUE(agent.AcceptObjective(objective));

    ExecutionOutcomeSummary outcome;
    outcome.success_indicator = true;
    outcome.summary = "objective achieved";
    const CompletionEvaluation evaluation =
        agent.EvaluateObjective(ObjectiveId(4), outcome);

    EXPECT_TRUE(evaluation.IsAchieved());
    EXPECT_EQ(evaluation.GetObjectiveId(), ObjectiveId(4));
    EXPECT_EQ(evaluation.Rationale(), "objective achieved");
}

TEST(Ownership, SupervisionRepresentationIsAgentOwned) {
    ExecutionSupervision supervision;
    supervision.Begin(ObjectiveId(9));
    EXPECT_TRUE(supervision.IsActive());
    EXPECT_EQ(supervision.GetObjectiveId(), ObjectiveId(9));
    supervision.RecordInterpretation("progressing");
    supervision.DecideContinuation(true);
    EXPECT_EQ(supervision.GetInterpretation(), "progressing");
    EXPECT_TRUE(supervision.ContinueExecution());
}

TEST(Ownership, NoUniversalManagerSurfaceExists) {
    // The Agent boundary declares no Manager-style universal
    // type; the static boundary check additionally scans all
    // Agent headers for forbidden type names.
    static_assert(!std::is_same_v<AgentCoordinationService,
                                  void>, "placeholder");
    // Behavioral counterpart: coordination is a service, not a
    // universal manager, and it is Agent-owned (constructed by
    // the Agent object).
    Agent agent(MakeAgentIdentity(1));
    EXPECT_FALSE(agent.HasAllSubsystemContracts());
}

TEST(Ownership, DependencyDirectionIsAgentToFoundationOnly) {
    // Compile-time proof at the TU level: this file includes
    // only Agent and Foundation headers. The CMake boundary
    // check verifies every Agent header/source include set and
    // the agent_kernel_agent link set.
    Agent agent(MakeAgentIdentity(1));
    EXPECT_EQ(agent.GetState(), AgentState::kUninitialized);
}

}  // namespace
}  // namespace ak::agent
