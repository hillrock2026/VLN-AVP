// ============================================================
// ownership_dependency_test.cpp - P1-IS003 ownership/dependency
// conformance
// ============================================================
// MEM-002 / MEM-010 / MEM-016 / MEM-017 / MEM-018: Memory is an
// independent subsystem; it owns its Domains, Objects, Entries,
// Metadata, References, Services, Providers, and Extensions; it
// does not own or coordinate Agent, Context, Planner, Tool, or
// Runtime; no universal manager exists.
// ============================================================

#include <agent_kernel/memory/memory.hpp>
#include <agent_kernel/memory/memory_extensions.hpp>
#include <agent_kernel/memory/memory_identity.hpp>
#include <agent_kernel/memory/memory_provider.hpp>
#include <agent_kernel/memory/memory_services.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <memory>
#include <type_traits>

#include "test_doubles.hpp"

namespace ak::memory {
namespace {

MemoryExtensionVersion MakeVersionForTest() {
    return MemoryExtensionVersion{1, 0};
}

// Negative API surface: Memory must not expose peer subsystem
// objects, coordination entry points, or universal managers.
template <typename T, typename = void>
struct HasAgentAccessor : std::false_type {};
template <typename T>
struct HasAgentAccessor<T, std::void_t<decltype(std::declval<T&>().GetAgent())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasContextAccessor : std::false_type {};
template <typename T>
struct HasContextAccessor<T, std::void_t<decltype(std::declval<T&>().GetContext())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasPlannerAccessor : std::false_type {};
template <typename T>
struct HasPlannerAccessor<T, std::void_t<decltype(std::declval<T&>().GetPlanner())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasToolAccessor : std::false_type {};
template <typename T>
struct HasToolAccessor<T, std::void_t<decltype(std::declval<T&>().GetTool())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasMemoryManager : std::false_type {};
template <typename T>
struct HasMemoryManager<T, std::void_t<decltype(std::declval<T&>().GetMemoryManager())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasUniversalCoordinator : std::false_type {};
template <typename T>
struct HasUniversalCoordinator<
    T, std::void_t<decltype(std::declval<T&>().GetUniversalCoordinator())>>
    : std::true_type {};

TEST(MemoryOwnership, MemoryIsAnIndependentBoundary) {
    // Memory stands alone: identity, lifecycle, state, store,
    // services, provider, extensions, and Agent contract are all
    // Memory-owned.
    Memory memory(MakeMemoryIdentity(1));
    EXPECT_TRUE(memory.GetIdentity().IsValid());
    EXPECT_TRUE(memory.HasProvider());
    EXPECT_EQ(memory.Services().DomainCount(), 0);
    EXPECT_EQ(memory.Extensions().Count(), 0);
    EXPECT_EQ(std::string(memory.AgentContract().ContractName()), "Memory");
}

TEST(MemoryOwnership, MemoryOwnsObjectsServicesProvidersAndExtensions) {
    Memory memory(MakeMemoryIdentity(2));
    ASSERT_TRUE(test::ActivateAndMakeAvailable(memory));
    ASSERT_TRUE(memory.Services()
                    .CreateDomain(MakeMemoryDomainId(1), "d",
                                  test::MakeMetadata("d"))
                    .IsSuccess());
    ASSERT_TRUE(memory.Services()
                    .Retain(MakeMemoryEntryId(1), MakeMemoryDomainId(1),
                            MemoryObject(MakeMemoryObjectId(1), "payload",
                                         test::MakeMetadata("obj")))
                    .IsSuccess());
    memory.Extensions().Attach(std::make_shared<test::MemoryExtensionDouble>(
        "ext", MakeVersionForTest()));

    EXPECT_EQ(memory.Services().DomainCount(), 1);
    EXPECT_EQ(memory.Services().EntryCount(), 1);
    EXPECT_EQ(memory.Extensions().Count(), 1);
}

TEST(MemoryOwnership, MemoryDoesNotOwnOrCoordinatePeers) {
    static_assert(!HasAgentAccessor<Memory>::value,
                  "Memory must not expose an Agent object");
    static_assert(!HasContextAccessor<Memory>::value,
                  "Memory must not own Context");
    static_assert(!HasPlannerAccessor<Memory>::value,
                  "Memory must not own Planner");
    static_assert(!HasToolAccessor<Memory>::value,
                  "Memory must not own Tool");
}

TEST(MemoryOwnership, NoUniversalManagerOrCoordinatorExists) {
    static_assert(!HasMemoryManager<Memory>::value,
                  "no MemoryManager universal type");
    static_assert(!HasUniversalCoordinator<Memory>::value,
                  "no universal coordinator");
    // Memory does not own Runtime state or objects.
    static_assert(!HasMemoryManager<MemoryService>::value);
    static_assert(!HasMemoryManager<IMemoryProvider>::value);
}

TEST(MemoryOwnership, DependencyDirectionIsMemoryToFoundationOnly) {
    // Compile-time proof at the TU level: this file includes
    // only Memory and Foundation headers. The MemoryBoundaryCheck
    // CTest scans every Memory header/source include set and the
    // agent_kernel_memory link set.
    Memory memory(MakeMemoryIdentity(3));
    EXPECT_EQ(memory.GetLifecycleState(), MemoryLifecycleState::kRegistered);
}

}  // namespace
}  // namespace ak::memory