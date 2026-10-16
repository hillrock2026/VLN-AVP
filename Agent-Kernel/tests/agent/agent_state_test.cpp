// ============================================================
// agent_state_test.cpp - P1-IS002 state conformance
// ============================================================
// AG-009/AG-0310: exactly one externally visible Agent
// architectural state model; state transitions are
// deterministic and Agent-owned; internal substates do not
// create new architectural states; Runtime cannot modify Agent
// state.
// ============================================================

#include <agent_kernel/agent/agent.hpp>
#include <agent_kernel/agent/agent_state.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <type_traits>

namespace ak::agent {
namespace {

// A trait that detects a public state setter on the Agent.
// The Agent exposes NO external state-mutation API: only its
// lifecycle methods may change state (SP-4).
template <typename T, typename = void>
struct HasSetState : std::false_type {};
template <typename T>
struct HasSetState<T, std::void_t<decltype(std::declval<T&>().SetState(
                          AgentState::kReady))>> : std::true_type {};

TEST(AgentState, ExposesExactlyOneArchitecturalState) {
    Agent agent(MakeAgentIdentity(1));
    EXPECT_EQ(agent.GetState(), AgentState::kUninitialized);
    EXPECT_EQ(agent.GetStateName(), "Uninitialized");
}

TEST(AgentState, CoversAllArchitecturalStates) {
    EXPECT_EQ(AgentStateName(AgentState::kUninitialized), "Uninitialized");
    EXPECT_EQ(AgentStateName(AgentState::kReady), "Ready");
    EXPECT_EQ(AgentStateName(AgentState::kCoordinating), "Coordinating");
    EXPECT_EQ(AgentStateName(AgentState::kSupervising), "Supervising");
    EXPECT_EQ(AgentStateName(AgentState::kSuspended), "Suspended");
    EXPECT_EQ(AgentStateName(AgentState::kTerminated), "Terminated");

    // Codes map 1:1 onto the Foundation-neutral lifecycle value.
    EXPECT_EQ(ToLifecycleState(AgentState::kReady).Value(),
              static_cast<std::uint8_t>(AgentState::kReady));
}

TEST(AgentState, TransitionsAreDeterministic) {
    EXPECT_TRUE(IsLegalAgentTransition(AgentState::kUninitialized,
                                       AgentState::kReady));
    EXPECT_FALSE(IsLegalAgentTransition(AgentState::kReady,
                                        AgentState::kReady));
    EXPECT_TRUE(ValidateAgentTransition(AgentState::kUninitialized,
                                        AgentState::kReady).Accepted());
    EXPECT_TRUE(ValidateAgentTransition(AgentState::kReady,
                                        AgentState::kTerminated).Accepted());
    EXPECT_TRUE(ValidateAgentTransition(AgentState::kCoordinating,
                                        AgentState::kSuspended).Rejected());
}

TEST(AgentState, OnlyAgentMethodsMutateState) {
    // No public setter exists: the Agent object owns its state
    // and only its lifecycle methods initiate transitions.
    static_assert(!HasSetState<Agent>::value,
                  "Agent must not expose an external state setter");
}

TEST(AgentState, StateRemainsAgentOwnedThroughLifecycle) {
    Agent agent(MakeAgentIdentity(1));
    ASSERT_TRUE(agent.Initialize().Accepted());
    EXPECT_EQ(agent.GetState(), AgentState::kReady);

    // A rejected transition leaves the state unchanged.
    const TransitionResult rejected = agent.EnterSupervising();
    EXPECT_TRUE(rejected.Rejected());
    EXPECT_EQ(agent.GetState(), AgentState::kReady);
}

}  // namespace
}  // namespace ak::agent
