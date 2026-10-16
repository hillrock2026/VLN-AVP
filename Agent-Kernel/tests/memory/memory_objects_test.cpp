// ============================================================
// memory_objects_test.cpp - P1-IS003 object model conformance
// ============================================================
// MEM-007 / MEM-019: Memory owns Domains, Objects, Entries,
// Metadata, and References; Entry belongs to one Domain and
// references one Object; References expose architectural
// identity only; collections are encapsulated behind the
// Memory Service boundary.
// ============================================================

#include <agent_kernel/memory/memory.hpp>
#include <agent_kernel/memory/memory_objects.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

#include "test_doubles.hpp"

namespace ak::memory {
namespace {

// Negative API surface: a Reference must expose no storage-
// oriented identifier (database id, address, index, handle).
template <typename T, typename = void>
struct HasStorageId : std::false_type {};
template <typename T>
struct HasStorageId<T, std::void_t<decltype(std::declval<T&>().GetStorageId())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasStorageAddress : std::false_type {};
template <typename T>
struct HasStorageAddress<T, std::void_t<decltype(std::declval<T&>().GetStorageAddress())>>
    : std::true_type {};

// Negative API surface: external consumers must not mutate a
// Memory Object directly.
template <typename T, typename = void>
struct HasSetContent : std::false_type {};
template <typename T>
struct HasSetContent<T, std::void_t<decltype(std::declval<T&>().SetContent(
                            std::string{}))>> : std::true_type {};

// Negative API surface: Memory must not expose its internal
// collection store directly.
template <typename T, typename = void>
struct HasPublicStore : std::false_type {};
template <typename T>
struct HasPublicStore<T, std::void_t<decltype(std::declval<T&>().GetStore())>>
    : std::true_type {};

TEST(MemoryObjects, DomainObjectEntryReferenceAreRepresented) {
    const MemoryDomainId domain_id = MakeMemoryDomainId(1);
    const MemoryObjectId object_id = MakeMemoryObjectId(10);
    const MemoryEntryId entry_id = MakeMemoryEntryId(100);

    MemoryDomain domain(domain_id, "episodic", test::MakeMetadata("domain"));
    MemoryObject object(object_id, "retained knowledge",
                        test::MakeMetadata("object", 2));
    MemoryEntry entry(entry_id, domain_id, object_id, test::MakeMetadata("entry"));
    MemoryReference reference(domain_id, object_id);

    EXPECT_EQ(domain.GetId(), domain_id);
    EXPECT_EQ(domain.GetName(), "episodic");
    EXPECT_EQ(object.GetId(), object_id);
    EXPECT_EQ(entry.GetId(), entry_id);
    EXPECT_EQ(entry.GetDomainId(), domain_id);
    EXPECT_EQ(entry.GetObjectId(), object_id);
    EXPECT_TRUE(reference.IsValid());
    EXPECT_EQ(reference.GetDomainId(), domain_id);
    EXPECT_EQ(reference.GetObjectId(), object_id);
}

TEST(MemoryObjects, EntryBelongsToOneDomainAndReferencesOneObject) {
    Memory memory(MakeMemoryIdentity(1));
    ASSERT_TRUE(test::ActivateAndMakeAvailable(memory));

    const MemoryDomainId domain_a = MakeMemoryDomainId(1);
    const MemoryDomainId domain_b = MakeMemoryDomainId(2);
    ASSERT_TRUE(memory.Services()
                    .CreateDomain(domain_a, "a", test::MakeMetadata("da"))
                    .IsSuccess());
    ASSERT_TRUE(memory.Services()
                    .CreateDomain(domain_b, "b", test::MakeMetadata("db"))
                    .IsSuccess());

    const MemoryObject object(MakeMemoryObjectId(1), "payload",
                              test::MakeMetadata("obj"));
    const auto retained = memory.Services().Retain(
        MakeMemoryEntryId(1), domain_a, object);
    ASSERT_TRUE(retained.IsSuccess());

    const auto entry = memory.Services().FindEntry(MakeMemoryEntryId(1));
    ASSERT_TRUE(entry.IsSuccess());
    EXPECT_EQ(entry.value.GetDomainId(), domain_a);
    EXPECT_NE(entry.value.GetDomainId(), domain_b);
    EXPECT_EQ(entry.value.GetObjectId(), object.GetId());
}

TEST(MemoryObjects, MetadataIsExtensibleAndRoundTrips) {
    MemoryMetadata metadata = test::MakeMetadata("knowledge", 3);
    metadata.core.description = "description";
    metadata.retention_policy = "keep";
    metadata.annotations.push_back("annotation-1");
    metadata.annotations.push_back("annotation-2");

    EXPECT_EQ(metadata.version, 3);
    ASSERT_EQ(metadata.annotations.size(), 2);

    Memory memory(MakeMemoryIdentity(2));
    ASSERT_TRUE(test::ActivateAndMakeAvailable(memory));
    ASSERT_TRUE(memory.Services()
                    .CreateDomain(MakeMemoryDomainId(1), "d",
                                  test::MakeMetadata("domain"))
                    .IsSuccess());
    const auto retained = memory.Services().Retain(
        MakeMemoryEntryId(1), MakeMemoryDomainId(1),
        MemoryObject(MakeMemoryObjectId(1), "payload", metadata));
    ASSERT_TRUE(retained.IsSuccess());

    const auto retrieved = memory.Services().Retrieve(MakeMemoryEntryId(1));
    ASSERT_TRUE(retrieved.IsSuccess());
    EXPECT_EQ(retrieved.value.GetMetadata(), metadata);
}

TEST(MemoryObjects, ReferenceExposesOnlyArchitecturalIdentity) {
    static_assert(!HasStorageId<MemoryReference>::value,
                  "Reference must not expose storage identifiers");
    static_assert(!HasStorageAddress<MemoryReference>::value,
                  "Reference must not expose storage addresses");

    Memory memory(MakeMemoryIdentity(3));
    ASSERT_TRUE(test::ActivateAndMakeAvailable(memory));
    ASSERT_TRUE(memory.Services()
                    .CreateDomain(MakeMemoryDomainId(1), "d",
                                  test::MakeMetadata("domain"))
                    .IsSuccess());
    ASSERT_TRUE(memory.Services()
                    .Retain(MakeMemoryEntryId(1), MakeMemoryDomainId(1),
                            MemoryObject(MakeMemoryObjectId(1), "p",
                                         test::MakeMetadata("obj")))
                    .IsSuccess());

    const auto reference =
        memory.Services().LookupReference(MakeMemoryObjectId(1));
    ASSERT_TRUE(reference.IsSuccess());
    EXPECT_EQ(reference.value.GetObjectId(), MakeMemoryObjectId(1));
    EXPECT_EQ(reference.value.GetDomainId(), MakeMemoryDomainId(1));
}

TEST(MemoryObjects, ObjectIsOpaqueToExternalMutation) {
    static_assert(!HasSetContent<MemoryObject>::value,
                  "Memory Object must not expose a content mutator");

    MemoryObject object(MakeMemoryObjectId(1), "content",
                        test::MakeMetadata("obj"));
    EXPECT_EQ(object.Content(), "content");
    // Read-only view only: const access, no mutation path.
    const MemoryObject& const_view = object;
    EXPECT_EQ(const_view.Content(), "content");
}

TEST(MemoryObjects, CollectionsAreEncapsulatedBehindServices) {
    static_assert(!HasPublicStore<Memory>::value,
                  "Memory must not expose its internal store");

    Memory memory(MakeMemoryIdentity(4));
    ASSERT_TRUE(test::ActivateAndMakeAvailable(memory));
    // All object access must go through the Memory Service
    // boundary; no other mutation path exists.
    EXPECT_EQ(memory.Services().DomainCount(), 0);
    EXPECT_EQ(memory.Services().EntryCount(), 0);
}

}  // namespace
}  // namespace ak::memory