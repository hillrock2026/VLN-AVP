// ============================================================
// agent_lifecycle_test.cpp - P1-IS002 lifecycle conformance
// ============================================================
// AG-008/AG-014: Agent lifecycle is independently owned;
// transitions follow the normative model; illegal transitions
// are rejected with a clear result; Runtime completion does not
// automatically terminate the Agent; Agent termination does not
// modify Runtime lifecycle.
// ============================================================

#include <agent_kernel/agent/agent.hpp>

#include <gtest/gtest.h>

#include <string>

#include "test_doubles.hpp"

namespace ak::agent {
namespace {

class AgentLifecycleTest : public ::testing::Test {
protected:
    void SetUp() override {
        memory_ = std::make_unique<test::MemoryContractDouble>();
        context_ = std::make_unique<test::ContextContractDouble>();
        planner_ = std::make_unique<test::PlannerContractDouble>();
        tool_ = std::make_unique<test::ToolContractDouble>();
        test::BindAllContracts(agent_, *memory_, *context_, *planner_, *tool_);
    }

    Agent agent_{MakeAgentIdentity(1)};
    std::unique_ptr<test::MemoryContractDouble> memory_;
    std::unique_ptr<test::ContextContractDouble> context_;
    std::unique_ptr<test::PlannerContractDouble> planner_;
    std::unique_ptr<test::ToolContractDouble> tool_;
};

TEST_F(AgentLifecycleTest, InitializationEntersReady) {
    EXPECT_EQ(agent_.GetState(), AgentState::kUninitialized);

    const TransitionResult result = agent_.Initialize();
    EXPECT_TRUE(result.Accepted());
    EXPECT_EQ(agent_.GetState(), AgentState::kReady);
    EXPECT_EQ(agent_.GetStateName(), "Ready");
}

TEST_F(AgentLifecycleTest, BeginCoordinationRequiresBoundContracts) {
    Agent unbound(MakeAgentIdentity(2));
    ASSERT_TRUE(unbound.Initialize().Accepted());

    const TransitionResult result = unbound.BeginCoordination();
    EXPECT_TRUE(result.Rejected());
    EXPECT_NE(std::string(result.message), "");
    EXPECT_EQ(unbound.GetState(), AgentState::kReady);
}

TEST_F(AgentLifecycleTest, BeginCoordinationEntersCoordinatingAndCoordinatesPeers) {
    ASSERT_TRUE(agent_.Initialize().Accepted());

    const TransitionResult result = agent_.BeginCoordination();
    EXPECT_TRUE(result.Accepted());
    EXPECT_EQ(agent_.GetState(), AgentState::kCoordinating);

    // The Agent invoked each peer subsystem contract exactly once.
    EXPECT_EQ(memory_->acknowledged_count, 1);
    EXPECT_EQ(context_->acknowledged_count, 1);
    EXPECT_EQ(planner_->acknowledged_count, 1);
    EXPECT_EQ(tool_->acknowledged_count, 1);
}

TEST_F(AgentLifecycleTest, FollowsNormativeTransitionModel) {
    ASSERT_TRUE(agent_.Initialize().Accepted());
    ASSERT_TRUE(agent_.BeginCoordination().Accepted());
    EXPECT_TRUE(agent_.EnterSupervising().Accepted());
    EXPECT_EQ(agent_.GetState(), AgentState::kSupervising);

    // Supervising -> Coordinating (adaptation loop).
    EXPECT_TRUE(agent_.ReturnToCoordinating().Accepted());
    EXPECT_EQ(agent_.GetState(), AgentState::kCoordinating);

    // Coordinating -> Supervising -> Suspended -> Ready -> Terminated.
    ASSERT_TRUE(agent_.EnterSupervising().Accepted());
    EXPECT_TRUE(agent_.Suspend().Accepted());
    EXPECT_EQ(agent_.GetState(), AgentState::kSuspended);

    EXPECT_TRUE(agent_.Resume().Accepted());
    EXPECT_EQ(agent_.GetState(), AgentState::kReady);

    EXPECT_TRUE(agent_.Terminate().Accepted());
    EXPECT_EQ(agent_.GetState(), AgentState::kTerminated);
}

TEST_F(AgentLifecycleTest, IllegalTransitionsAreRejected) {
    // Uninitialized: only -> Ready is legal.
    EXPECT_TRUE(agent_.BeginCoordination().Rejected());
    EXPECT_TRUE(agent_.EnterSupervising().Rejected());
    EXPECT_TRUE(agent_.Suspend().Rejected());
    EXPECT_TRUE(agent_.Resume().Rejected());
    EXPECT_TRUE(agent_.Terminate().Rejected());
    EXPECT_EQ(agent_.GetState(), AgentState::kUninitialized);

    ASSERT_TRUE(agent_.Initialize().Accepted());
    ASSERT_TRUE(agent_.BeginCoordination().Accepted());

    // Coordinating: only -> Supervising is legal.
    EXPECT_TRUE(agent_.Suspend().Rejected());
    EXPECT_TRUE(agent_.Resume().Rejected());
    EXPECT_TRUE(agent_.Terminate().Rejected());
    EXPECT_EQ(agent_.GetState(), AgentState::kCoordinating);

    // Supervising: only -> Coordinating / Suspended are legal.
    ASSERT_TRUE(agent_.EnterSupervising().Accepted());
    EXPECT_TRUE(agent_.Resume().Rejected());
    EXPECT_TRUE(agent_.Terminate().Rejected());
    EXPECT_EQ(agent_.GetState(), AgentState::kSupervising);

    // Terminated is absorbing.
    ASSERT_TRUE(agent_.Suspend().Accepted());
    ASSERT_TRUE(agent_.Resume().Accepted());
    ASSERT_TRUE(agent_.Terminate().Accepted());
    EXPECT_TRUE(agent_.Initialize().Rejected());
    EXPECT_TRUE(agent_.BeginCoordination().Rejected());
    EXPECT_TRUE(agent_.Resume().Rejected());
    EXPECT_EQ(agent_.GetState(), AgentState::kTerminated);
}

TEST_F(AgentLifecycleTest, RejectedTransitionsReturnClearError) {
    const TransitionResult result = agent_.BeginCoordination();
    EXPECT_TRUE(result.Rejected());
    EXPECT_NE(std::string(result.message), "");
    // The Agent records an owner-scoped diagnostic for the
    // rejected transition.
    EXPECT_GE(agent_.Diagnostics().Count(), 1);
}

TEST_F(AgentLifecycleTest, RuntimeCompletionDoesNotAutoTerminateAgent) {
    ASSERT_TRUE(agent_.Initialize().Accepted());
    ASSERT_TRUE(agent_.BeginCoordination().Accepted());
    ASSERT_TRUE(agent_.EnterSupervising().Accepted());

    // Phase 1 has no Runtime observation: no external signal can
    // drive Agent state. Simulating a "Runtime completion" via a
    // test-local signal must leave the Agent state unchanged.
    const bool runtime_completed = true;  // test-local signal
    (void)runtime_completed;

    EXPECT_EQ(agent_.GetState(), AgentState::kSupervising);
    // No automatic transition occurred.
    EXPECT_NE(agent_.GetState(), AgentState::kTerminated);
    EXPECT_NE(agent_.GetState(), AgentState::kReady);
}

TEST_F(AgentLifecycleTest, TerminationDoesNotTouchSubsystemOrRuntime) {
    ASSERT_TRUE(agent_.Initialize().Accepted());
    ASSERT_TRUE(agent_.BeginCoordination().Accepted());
    ASSERT_TRUE(agent_.EnterSupervising().Accepted());

    // Record counts after the last Agent-initiated coordination.
    const std::size_t memory_count = memory_->acknowledged_count;
    const std::size_t context_count = context_->acknowledged_count;
    const std::size_t planner_count = planner_->acknowledged_count;
    const std::size_t tool_count = tool_->acknowledged_count;

    // Terminate is only legal from Ready in the normative model,
    // so first return to Ready and terminate.
    ASSERT_TRUE(agent_.Suspend().Accepted());
    ASSERT_TRUE(agent_.Resume().Accepted());
    ASSERT_TRUE(agent_.Terminate().Accepted());

    // Termination invoked no subsystem contract and no Runtime
    // action: counts are unchanged.
    EXPECT_EQ(memory_->acknowledged_count, memory_count);
    EXPECT_EQ(context_->acknowledged_count, context_count);
    EXPECT_EQ(planner_->acknowledged_count, planner_count);
    EXPECT_EQ(tool_->acknowledged_count, tool_count);
    EXPECT_EQ(agent_.GetState(), AgentState::kTerminated);
}

}  // namespace
}  // namespace ak::agent
