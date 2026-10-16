// ============================================================
// memory_provider_test.cpp - P1-IS003 provider conformance
// ============================================================
// MEM-009 / MEM-015: providers remain below Memory Services;
// provider technology does not define Memory; provider failures
// become Memory-owned results and Memory-owned operational
// transitions; providers never own lifecycle/state.
// ============================================================

#include <agent_kernel/memory/memory.hpp>
#include <agent_kernel/memory/memory_provider.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <type_traits>

#include "test_doubles.hpp"

namespace ak::memory {
namespace {

// Negative API surface: the provider interface must expose no
// Memory lifecycle, operational state, or peer coordination.
template <typename T, typename = void>
struct HasLifecycleHandle : std::false_type {};
template <typename T>
struct HasLifecycleHandle<T, std::void_t<decltype(std::declval<T&>().GetLifecycleState())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasCoordinatePeer : std::false_type {};
template <typename T>
struct HasCoordinatePeer<T, std::void_t<decltype(std::declval<T&>().CoordinatePlanner())>>
    : std::true_type {};

TEST(MemoryProvider, ProvidersSitBelowTheServiceBoundary) {
    Memory memory(MakeMemoryIdentity(1));
    auto recording = std::make_shared<test::RecordingMemoryProvider>();
    (void)memory.SetProvider(recording);
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
    EXPECT_EQ(recording->store_calls, 1);
    EXPECT_EQ(recording->load_calls, 0);

    const auto retrieved = memory.Services().Retrieve(MakeMemoryEntryId(1));
    ASSERT_TRUE(retrieved.IsSuccess());
    EXPECT_EQ(recording->load_calls, 1);
    EXPECT_EQ(retrieved.value.Content(), "payload");
}

TEST(MemoryProvider, ProviderInterfaceHasNoStateOrCoordinationSurface) {
    static_assert(!HasLifecycleHandle<IMemoryProvider>::value,
                  "provider must not own Memory lifecycle state");
    static_assert(!HasCoordinatePeer<IMemoryProvider>::value,
                  "provider must not coordinate peers");
}

TEST(MemoryProvider, ProviderTechnologyDoesNotDefineMemoryIdentity) {
    const MemoryIdentity identity = MakeMemoryIdentity(7);

    Memory memory_a(identity, std::make_shared<test::RecordingMemoryProvider>());
    Memory memory_b(identity, std::make_shared<test::FailingMemoryProvider>(false, false, false));

    EXPECT_EQ(memory_a.GetIdentity(), identity);
    EXPECT_EQ(memory_b.GetIdentity(), identity);
    EXPECT_EQ(memory_a.GetIdentity(), memory_b.GetIdentity());

    // Both expose the same Memory-owned lifecycle semantics.
    EXPECT_TRUE(memory_a.InitializeLifecycle().IsSuccess());
    EXPECT_TRUE(memory_b.InitializeLifecycle().IsSuccess());
    EXPECT_EQ(memory_a.GetLifecycleState(), memory_b.GetLifecycleState());
}

TEST(MemoryProvider, ProviderFailureMapsToMemoryOwnedResultAndDegradedState) {
    Memory memory(MakeMemoryIdentity(2));
    auto failing = std::make_shared<test::FailingMemoryProvider>(true, true, true);
    (void)memory.SetProvider(failing);
    ASSERT_TRUE(test::ActivateAndMakeAvailable(memory));
    ASSERT_EQ(memory.GetOperationalState(), MemoryOperationalState::kAvailable);
    ASSERT_TRUE(memory.Services()
                    .CreateDomain(MakeMemoryDomainId(1), "d",
                                  test::MakeMetadata("d"))
                    .IsSuccess());

    const auto retained = memory.Services().Retain(
        MakeMemoryEntryId(1), MakeMemoryDomainId(1),
        MemoryObject(MakeMemoryObjectId(1), "payload", test::MakeMetadata("obj")));

    // Memory-owned result: Failure, not a provider exception.
    EXPECT_EQ(retained.status, MemoryResultStatus::kFailure);
    EXPECT_NE(std::string(retained.message), "");

    // Memory-owned operational consequence: Available -> Degraded.
    EXPECT_EQ(memory.GetOperationalState(), MemoryOperationalState::kDegraded);
}

TEST(MemoryProvider, MemoryRetainsOperationalControlAfterProviderFailure) {
    Memory memory(MakeMemoryIdentity(3));
    auto failing = std::make_shared<test::FailingMemoryProvider>(true, true, true);
    (void)memory.SetProvider(failing);
    ASSERT_TRUE(test::ActivateAndMakeAvailable(memory));
    ASSERT_TRUE(memory.Services()
                    .CreateDomain(MakeMemoryDomainId(1), "d",
                                  test::MakeMetadata("d"))
                    .IsSuccess());

    (void)memory.Services().Retain(
        MakeMemoryEntryId(1), MakeMemoryDomainId(1),
        MemoryObject(MakeMemoryObjectId(1), "payload", test::MakeMetadata("obj")));
    ASSERT_EQ(memory.GetOperationalState(), MemoryOperationalState::kDegraded);

    // Memory still owns the operational state machine: Degraded ->
    // Available -> Busy -> Degraded is fully Memory-controlled.
    EXPECT_TRUE(memory.MarkAvailable().IsSuccess());
    EXPECT_EQ(memory.GetOperationalState(), MemoryOperationalState::kAvailable);
    EXPECT_TRUE(memory.MarkBusy().IsSuccess());
    EXPECT_TRUE(memory.MarkDegraded().IsSuccess());
    EXPECT_EQ(memory.GetOperationalState(), MemoryOperationalState::kDegraded);
}

TEST(MemoryProvider, InProcessProviderRoundTripAndRemove) {
    InProcessMemoryProvider provider;
    EXPECT_EQ(provider.TechnologyName(), "in-process");

    MemoryMetadata metadata = test::MakeMetadata("obj", 2);
    EXPECT_TRUE(provider.StoreObject(MakeMemoryObjectId(1), "content", metadata)
                    .IsSuccess());
    EXPECT_EQ(provider.StoredCount(), 1);

    std::string content;
    MemoryMetadata loaded;
    EXPECT_TRUE(provider.LoadObject(MakeMemoryObjectId(1), content, loaded)
                    .IsSuccess());
    EXPECT_EQ(content, "content");
    EXPECT_EQ(loaded, metadata);

    EXPECT_EQ(provider.LoadObject(MakeMemoryObjectId(2), content, loaded).status,
              ProviderStatus::kNotFound);
    EXPECT_TRUE(provider.RemoveObject(MakeMemoryObjectId(1)).IsSuccess());
    EXPECT_EQ(provider.RemoveObject(MakeMemoryObjectId(1)).status,
              ProviderStatus::kNotFound);
}

}  // namespace
}  // namespace ak::memory