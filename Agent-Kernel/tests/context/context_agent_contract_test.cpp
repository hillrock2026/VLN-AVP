// ============================================================
// context_agent_contract_test.cpp - P1-IS004 Agent-Context
// interaction conformance
// ============================================================
// CTX-004 / CTX-010: Agent is the sole coordinator of Context;
// the Agent consumes Context Services through the Agent-facing
// contract; the Agent cannot own or directly mutate Context
// lifecycle/state; Context never coordinates the Agent.
// ============================================================

#include <agent_kernel/context/context.hpp>
#include <agent_kernel/context/context_agent_contract.hpp>

#include <gtest/gtest.h>

#include <string>
#include <type_traits>

#include "test_doubles.hpp"

namespace ak::context {
namespace {

// Negative API surface: the Agent-facing contract must not own
// or directly mutate Context lifecycle/state, and must expose no
// Agent coordination target.
template <typename T, typename = void>
struct HasRequestLifecycleParticipation : std::false_type {};
template <typename T>
struct HasRequestLifecycleParticipation<
    T, std::void_t<decltype(std::declval<T&>().RequestLifecycleParticipation())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasDirectLifecycleMutation : std::false_type {};
template <typename T>
struct HasDirectLifecycleMutation<
    T, std::void_t<decltype(std::declval<T&>().SetLifecycle(
           std::declval<ContextLifecycleState>()))>> : std::true_type {};

template <typename T, typename = void>
struct HasDirectStateMutation : std::false_type {};
template <typename T>
struct HasDirectStateMutation<
    T, std::void_t<decltype(std::declval<T&>().SetOperationalState(
           std::declval<ContextOperationalState>()))>> : std::true_type {};

template <typename T, typename = void>
struct HasGetAgent : std::false_type {};
template <typename T>
struct HasGetAgent<T, std::void_t<decltype(std::declval<T&>().GetAgent())>>
    : std::true_type {};

TEST(ContextAgentContract, ContractIsTheAgentFacingContextSurface) {
    Context context(MakeContextIdentity(1));
    EXPECT_EQ(std::string(context.AgentContract().ContractName()), "Context");

    // The Agent consumes all five service responsibilities
    // through the contract.
    const ContextObjectId object_id = MakeContextObjectId(1);
    ASSERT_TRUE(context.AgentContract()
                    .Creation()
                    .CreateObject(object_id, "working_state", "payload",
                                  test::MakeMetadata("obj"))
                    .IsSuccess());
    ASSERT_TRUE(context.AgentContract().Creation().InitializeObject(object_id).IsSuccess());
    ASSERT_TRUE(context.AgentContract().Creation().ActivateObject(object_id).IsSuccess());

    const auto view = context.AgentContract().Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_EQ(view.value.lifecycle, ContextLifecycleState::kActive);

    ASSERT_TRUE(context.AgentContract().Update().BeginUpdate(object_id).IsSuccess());
    ASSERT_TRUE(context.AgentContract()
                    .Update()
                    .ApplyUpdate(object_id, "evolved", test::MakeMetadata("v2"))
                    .IsSuccess());
    ASSERT_TRUE(context.AgentContract().Update().CompleteUpdate(object_id).IsSuccess());

    const ContextObjectId other = MakeContextObjectId(2);
    ASSERT_TRUE(context.AgentContract().Creation().CreateObject(
                    other, "execution_context", "payload",
                    test::MakeMetadata("obj2"))
                    .IsSuccess());
    ASSERT_TRUE(context.AgentContract().Creation().InitializeObject(other).IsSuccess());
    ASSERT_TRUE(context.AgentContract().Creation().ActivateObject(other).IsSuccess());
    ASSERT_TRUE(context.AgentContract()
                    .Composition()
                    .ComposeRelationship(MakeContextRelationshipId(1), object_id,
                                         other, "informs",
                                         test::MakeMetadata("rel"))
                    .IsSuccess());

    ASSERT_TRUE(context.AgentContract().Release().ReleaseObject(other).IsSuccess());
    EXPECT_EQ(context.AgentContract().Release().ReleaseObject(other).status,
              ContextResultStatus::kReleased);
}

TEST(ContextAgentContract, AgentRequestsButDoesNotOwnOrMutateState) {
    // The Agent-facing contract exposes no lifecycle/state
    // authority and no direct mutation surface.
    static_assert(!HasRequestLifecycleParticipation<ContextAgentContract>::value,
                  "the Agent cannot acquire Context lifecycle authority");
    static_assert(!HasDirectLifecycleMutation<ContextAgentContract>::value,
                  "the Agent cannot directly mutate Context lifecycle");
    static_assert(!HasDirectStateMutation<ContextAgentContract>::value,
                  "the Agent cannot directly mutate Context state");
}

TEST(ContextAgentContract, ContextDoesNotCoordinateTheAgent) {
    // Context exposes no Agent object and no Agent coordination
    // entry point anywhere on its service surface.
    static_assert(!HasGetAgent<Context>::value,
                  "Context must not own or coordinate an Agent");
    static_assert(!HasGetAgent<ContextAgentContract>::value,
                  "the Agent-facing contract must not own an Agent");
}

TEST(ContextAgentContract, ServicesAreContextOwned) {
    // The services returned through the contract remain
    // Context-owned: the same service instance is reachable from
    // the Context root and from the contract.
    Context context(MakeContextIdentity(1));
    EXPECT_EQ(&context.AgentContract().Creation(), &context.Creation());
    EXPECT_EQ(&context.AgentContract().Access(), &context.Access());
    EXPECT_EQ(&context.AgentContract().Update(), &context.Update());
    EXPECT_EQ(&context.AgentContract().Composition(), &context.Composition());
    EXPECT_EQ(&context.AgentContract().Release(), &context.Release());
}

}  // namespace
}  // namespace ak::context
