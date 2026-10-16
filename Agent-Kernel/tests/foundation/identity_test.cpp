// ============================================================
// identity_test.cpp - P1-IS001 Foundation identity tests
// ============================================================
// Verifies the neutral, opaque identity representation:
// - immutable value identity
// - validity, comparison, hashing, serialization
// - typed identity keeps owner domains separate
// - identity contracts are generic (no subsystem types)
// ============================================================

#include <agent_kernel/foundation/kernel_contracts.hpp>
#include <agent_kernel/foundation/kernel_identity.hpp>

#include <gtest/gtest.h>

#include <unordered_set>

namespace ak {
namespace {

struct AgentTag {};
struct MemoryTag {};

TEST(KernelIdentity, DefaultIsInvalid) {
    KernelIdentity identity;
    EXPECT_FALSE(identity.IsValid());
    EXPECT_EQ(identity.Value(), 0);
}

TEST(KernelIdentity, ExplicitValueIsValid) {
    KernelIdentity identity(42);
    EXPECT_TRUE(identity.IsValid());
    EXPECT_EQ(identity.Value(), 42);
}

TEST(KernelIdentity, IsImmutableValueType) {
    KernelIdentity identity(7);
    EXPECT_EQ(identity.ToString(), "7");
    EXPECT_EQ(identity.Value(), 7);
    // A copy observes the same value and can be compared.
    KernelIdentity copy = identity;
    EXPECT_EQ(copy, identity);
    EXPECT_FALSE(copy != identity);
}

TEST(KernelIdentity, SupportsOrdering) {
    KernelIdentity low(1);
    KernelIdentity high(2);
    EXPECT_LT(low, high);
    EXPECT_GT(high, low);
}

TEST(KernelIdentity, SupportsHashing) {
    std::unordered_set<KernelIdentity> set;
    set.insert(KernelIdentity(100));
    set.insert(KernelIdentity(100));
    set.insert(KernelIdentity(101));
    EXPECT_EQ(set.size(), 2);
    EXPECT_NE(set.find(KernelIdentity(100)), set.end());
}

TEST(TypedKernelIdentity, KeepsOwnerDomainsDistinct) {
    TypedKernelIdentity<AgentTag> agent(1);
    TypedKernelIdentity<MemoryTag> memory(1);
    // Same underlying value but distinct owner-domain types.
    EXPECT_EQ(agent.Value(), memory.Value());
    static_assert(!std::is_same_v<decltype(agent), decltype(memory)>,
                  "distinct owner domains must not be the same type");
}

TEST(KernelIdentityContract, TraitRecognizesNeutralIdentities) {
    static_assert(is_kernel_identity_v<KernelIdentity>);
    static_assert(is_kernel_identity_v<TypedKernelIdentity<AgentTag>>);
    static_assert(!is_kernel_identity_v<int>);
    static_assert(!is_kernel_identity_v<std::string>);
}

TEST(KernelIdentityContract, AssertValidIdentityCompilesForNeutralTypes) {
    AssertValidIdentity<KernelIdentity>();
    AssertValidIdentity<TypedKernelIdentity<AgentTag>>();
}

}  // namespace
}  // namespace ak