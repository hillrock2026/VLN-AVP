// ============================================================
// tool_identity_test.cpp - P1-IS006 Rev2 Chapter 33.1
// ============================================================
// Identity tests: empty identity rejection (TOL-111), identity
// equality and immutability (TOL-013/014/015), distinct Tool
// identity, and Tool-owned identity semantics (TOL-016).
// ============================================================

#include <agent_kernel/tool/tool_identity.hpp>

#include <gtest/gtest.h>

#include <stdexcept>
#include <string>
#include <type_traits>

namespace ak::tool {
namespace {

TEST(ToolIdentity, TOL_111_EmptyIdentityRejected) {
    EXPECT_THROW(ToolId(""), std::invalid_argument);
    EXPECT_THROW(ToolId("   "), std::invalid_argument);
    EXPECT_THROW(ToolId("\t"), std::invalid_argument);
    EXPECT_THROW(CapabilityId(""), std::invalid_argument);
    EXPECT_THROW(CapabilityId(" \n"), std::invalid_argument);
    EXPECT_THROW(ProviderId(""), std::invalid_argument);
    EXPECT_THROW(ProviderId("   "), std::invalid_argument);
}

TEST(ToolIdentity, TOL_013_ToolIdValueSemantics) {
    const ToolId id("kernel-tool");
    EXPECT_EQ(id.Value(), "kernel-tool");
    EXPECT_FALSE(id.Empty());
    EXPECT_EQ(id, ToolId("kernel-tool"));
    EXPECT_NE(id, ToolId("other-tool"));

    const ToolId copy = id;
    EXPECT_EQ(copy, id);
    EXPECT_EQ(copy.Value(), "kernel-tool");
    EXPECT_TRUE(id.Value() == copy.Value());
}

TEST(ToolIdentity, TOL_014_CapabilityIdValueSemantics) {
    const CapabilityId id("capability-a");
    EXPECT_EQ(id.Value(), "capability-a");
    EXPECT_FALSE(id.Empty());
    EXPECT_EQ(id, CapabilityId("capability-a"));
    EXPECT_NE(id, CapabilityId("capability-b"));

    const CapabilityId copy = id;
    EXPECT_EQ(copy, id);
    EXPECT_EQ(copy.Value(), "capability-a");
}

TEST(ToolIdentity, TOL_015_ProviderIdValueSemantics) {
    const ProviderId id("provider-1");
    EXPECT_EQ(id.Value(), "provider-1");
    EXPECT_FALSE(id.Empty());
    EXPECT_EQ(id, ProviderId("provider-1"));
    EXPECT_NE(id, ProviderId("provider-2"));

    const ProviderId copy = id;
    EXPECT_EQ(copy, id);
    EXPECT_EQ(copy.Value(), "provider-1");
}

TEST(ToolIdentity, TOL_016_IdentityIsToolOwned) {
    // Identity types are value types owned by Tool; they are
    // not default-constructible (a Tool root always fixes its
    // identity at construction, TOL-081) and are not Runtime
    // identities.
    static_assert(!std::is_default_constructible_v<ToolId>,
                  "ToolId must be constructed with an identity value");
    static_assert(!std::is_default_constructible_v<CapabilityId>,
                  "CapabilityId must be constructed with an identity value");
    static_assert(!std::is_default_constructible_v<ProviderId>,
                  "ProviderId must be constructed with an identity value");
    static_assert(std::is_copy_constructible_v<ToolId>);
    static_assert(std::is_copy_assignable_v<ProviderId>);
}

}  // namespace
}  // namespace ak::tool