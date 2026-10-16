// ============================================================
// memory_identity_test.cpp - P1-IS003 identity conformance
// ============================================================
// MEM-019 / MEM-002: Memory identity is stable, independent of
// implementation technology, distinct from other owner identity
// domains, and not derived from provider technology.
// ============================================================

#include <agent_kernel/memory/memory.hpp>
#include <agent_kernel/memory/memory_identity.hpp>

#include <gtest/gtest.h>

#include <concepts>
#include <cstddef>
#include <cstdint>
#include <string>
#include <type_traits>

#include "test_doubles.hpp"

namespace ak::memory {
namespace {

TEST(MemoryIdentity, IsValidAndOwned) {
    const MemoryIdentity identity = MakeMemoryIdentity(42);
    EXPECT_TRUE(identity.IsValid());
    EXPECT_EQ(identity.Value(), 42);
    EXPECT_EQ(identity.ToString(), "42");

    const MemoryIdentity invalid;
    EXPECT_FALSE(invalid.IsValid());
}

TEST(MemoryIdentity, IsValueType) {
    static_assert(std::is_copy_constructible_v<MemoryIdentity>);
    static_assert(std::is_nothrow_move_constructible_v<MemoryIdentity>);
    static_assert(std::equality_comparable<MemoryIdentity>);
    static_assert(std::equality_comparable<MemoryDomainId>);
    static_assert(std::equality_comparable<MemoryObjectId>);
    static_assert(std::equality_comparable<MemoryEntryId>);
}

TEST(MemoryIdentity, IdentityDomainsAreDistinct) {
    static_assert(!std::is_same_v<MemoryIdentity, MemoryDomainId>);
    static_assert(!std::is_same_v<MemoryIdentity, MemoryObjectId>);
    static_assert(!std::is_same_v<MemoryIdentity, MemoryEntryId>);
    static_assert(!std::is_same_v<MemoryObjectId, MemoryEntryId>);
}

TEST(MemoryIdentity, IsComparableAndHashable) {
    const MemoryObjectId a = MakeMemoryObjectId(7);
    const MemoryObjectId b = MakeMemoryObjectId(7);
    const MemoryObjectId c = MakeMemoryObjectId(8);

    EXPECT_EQ(a, b);
    EXPECT_NE(a, c);

    const std::size_t hash_a = std::hash<MemoryObjectId>{}(a);
    const std::size_t hash_b = std::hash<MemoryObjectId>{}(b);
    EXPECT_EQ(hash_a, hash_b);
}

TEST(MemoryIdentity, MemoryCarriesOwnedIdentity) {
    const Memory memory(MakeMemoryIdentity(99));
    EXPECT_EQ(memory.GetIdentity(), MakeMemoryIdentity(99));
}

TEST(MemoryIdentity, IdentityIsIndependentOfProviderTechnology) {
    // Replacing the provider technology does not change Memory
    // architectural identity or Memory-owned state semantics.
    Memory memory(MakeMemoryIdentity(5));
    auto recording = std::make_shared<test::RecordingMemoryProvider>();
    auto replaced = memory.SetProvider(recording);
    ASSERT_NE(replaced, nullptr);
    EXPECT_TRUE(memory.HasProvider());
    EXPECT_EQ(memory.GetIdentity(), MakeMemoryIdentity(5));

    const MemoryIdentity first = memory.GetIdentity();
    auto failing = std::make_shared<test::FailingMemoryProvider>(false, false, false);
    (void)memory.SetProvider(failing);
    EXPECT_EQ(memory.GetIdentity(), first);
    EXPECT_EQ(memory.GetIdentity(), MakeMemoryIdentity(5));
}

}  // namespace
}  // namespace ak::memory