// ============================================================
// registry_test.cpp - P1-IS001 registration boundary tests
// ============================================================
// Verifies:
// - OwnerScopedRegistry provides neutral owner-scoped
//   registration, lookup, enumeration, and removal.
// - Registration is mechanical containment: it does not
//   transfer architectural ownership.
// - A Foundation registry is not a Runtime Capability Resolver.
// ============================================================

#include <agent_kernel/foundation/kernel_identity.hpp>
#include <agent_kernel/foundation/kernel_registry.hpp>

#include <gtest/gtest.h>

#include <memory>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

namespace ak {
namespace {

// ------------------------------------------------------------
// SFINAE member detectors (capability-resolver absence)
// ------------------------------------------------------------
template <typename T, typename = void>
struct HasResolveCapability : std::false_type {};
template <typename T>
struct HasResolveCapability<
    T, std::void_t<decltype(std::declval<T&>().ResolveCapability(
           std::declval<const char*>()))>> : std::true_type {};

template <typename T, typename = void>
struct HasBind : std::false_type {};
template <typename T>
struct HasBind<T, std::void_t<decltype(std::declval<T&>().Bind(
                      std::declval<const char*>()))>> : std::true_type {};

template <typename T, typename = void>
struct HasExecute : std::false_type {};
template <typename T>
struct HasExecute<T, std::void_t<decltype(std::declval<T&>().Execute(
                         std::declval<const char*>()))>> : std::true_type {};

// ------------------------------------------------------------
// Test value type with destruction accounting
// ------------------------------------------------------------
struct Entry {
    explicit Entry(int v) : value(v) {}

    int value;
};

struct EntryWithDtor {
    explicit EntryWithDtor(int v) : value(v) {}
    ~EntryWithDtor() { ++destroyCount; }

    int value;
    static int destroyCount;
};
int EntryWithDtor::destroyCount = 0;

using TestRegistry = OwnerScopedRegistry<KernelIdentity, EntryWithDtor>;

TEST(OwnerScopedRegistry, RegisterFindContains) {
    TestRegistry registry;
    KernelIdentity key(100);

    EXPECT_FALSE(registry.Contains(key));
    EXPECT_EQ(registry.Find(key), nullptr);

    registry.Register(key, std::make_unique<EntryWithDtor>(7));

    EXPECT_TRUE(registry.Contains(key));
    EXPECT_EQ(registry.Count(), 1);
    ASSERT_NE(registry.Find(key), nullptr);
    EXPECT_EQ(registry.Find(key)->value, 7);
}

TEST(OwnerScopedRegistry, UnregisterReturnsOwnershipToCaller) {
    TestRegistry registry;
    KernelIdentity key(200);

    registry.Register(key, std::make_unique<EntryWithDtor>(9));
    EXPECT_EQ(registry.Count(), 1);

    // Unregister transfers the mechanical ownership back to the
    // owning subsystem; the registry does not retain it.
    std::unique_ptr<EntryWithDtor> returned = registry.Unregister(key);
    ASSERT_NE(returned, nullptr);
    EXPECT_EQ(returned->value, 9);
    EXPECT_EQ(registry.Count(), 0);
    EXPECT_FALSE(registry.Contains(key));

    // The caller (owner) controls destruction.
    int before = EntryWithDtor::destroyCount;
    returned.reset();
    EXPECT_EQ(EntryWithDtor::destroyCount, before + 1);
}

TEST(OwnerScopedRegistry, ContainmentIsMechanical) {
    // Clearing the registry destroys mechanically contained
    // values; this is container behavior, not architectural
    // ownership transfer.
    int before = EntryWithDtor::destroyCount;
    {
        TestRegistry registry;
        registry.Register(KernelIdentity(1), std::make_unique<EntryWithDtor>(1));
        registry.Register(KernelIdentity(2), std::make_unique<EntryWithDtor>(2));
        EXPECT_EQ(registry.Count(), 2);
        registry.Clear();
        EXPECT_EQ(registry.Count(), 0);
        EXPECT_EQ(EntryWithDtor::destroyCount, before + 2);
    }
}

TEST(OwnerScopedRegistry, EnumeratesKeys) {
    TestRegistry registry;
    registry.Register(KernelIdentity(1), std::make_unique<EntryWithDtor>(1));
    registry.Register(KernelIdentity(2), std::make_unique<EntryWithDtor>(2));

    std::vector<KernelIdentity> keys = registry.Enumerate();
    EXPECT_EQ(keys.size(), 2);
}

TEST(OwnerScopedRegistry, IsNotACapabilityResolver) {
    // A Foundation registry is not the Runtime Capability
    // Resolver: no capability, binding, or execution API.
    static_assert(!HasResolveCapability<TestRegistry>::value,
                  "registry must not resolve capabilities");
    static_assert(!HasBind<TestRegistry>::value,
                  "registry must not bind capabilities");
    static_assert(!HasExecute<TestRegistry>::value,
                  "registry must not execute anything");
}

}  // namespace
}  // namespace ak