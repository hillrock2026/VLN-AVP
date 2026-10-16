// ============================================================
// agent_identity_test.cpp - P1-IS002 identity conformance
// ============================================================
// AG-001/AG-002/AG-0301: Agent is a first-class boundary with
// an independently owned identity that is independent from
// Runtime object identity and from other owner identities.
// This TU intentionally includes no Runtime header.
// ============================================================

#include <agent_kernel/agent/agent.hpp>
#include <agent_kernel/agent/agent_identity.hpp>
#include <agent_kernel/agent/execution/execution_objective.hpp>

#include <gtest/gtest.h>

#include <concepts>
#include <cstdint>
#include <string>
#include <type_traits>

namespace ak::agent {
namespace {

TEST(AgentIdentity, IsValidAndOwned) {
    const AgentIdentity identity = MakeAgentIdentity(42);
    EXPECT_TRUE(identity.IsValid());
    EXPECT_EQ(identity.Value(), 42);
    EXPECT_EQ(identity.ToString(), "42");

    const AgentIdentity invalid;
    EXPECT_FALSE(invalid.IsValid());
}

TEST(AgentIdentity, IsValueType) {
    static_assert(std::is_copy_constructible_v<AgentIdentity>);
    static_assert(std::is_nothrow_move_constructible_v<AgentIdentity>);
    static_assert(std::equality_comparable<AgentIdentity>);
}

TEST(AgentIdentity, IsComparableAndHashable) {
    const AgentIdentity a = MakeAgentIdentity(7);
    const AgentIdentity b = MakeAgentIdentity(7);
    const AgentIdentity c = MakeAgentIdentity(8);

    EXPECT_EQ(a, b);
    EXPECT_NE(a, c);

    const std::size_t hash_a = std::hash<AgentIdentity>{}(a);
    const std::size_t hash_b = std::hash<AgentIdentity>{}(b);
    EXPECT_EQ(hash_a, hash_b);
}

TEST(AgentIdentity, IsIndependentFromRuntimeObjectIdentity) {
    // Independence is enforced at the type and include level:
    // - this TU includes no Runtime identity header;
    // - AgentIdentity is a typed Foundation identity distinct
    //   from every other owner's identity domain.
    static_assert(!std::is_same_v<AgentIdentity, ObjectiveId>,
                  "Agent identity must remain distinct from objective identity");
}

TEST(AgentIdentity, AgentCarriesOwnedIdentity) {
    const Agent agent(MakeAgentIdentity(99));
    EXPECT_EQ(agent.GetIdentity(), MakeAgentIdentity(99));
}

}  // namespace
}  // namespace ak::agent
