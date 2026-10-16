// ============================================================
// memory_services_test.cpp - P1-IS003 service conformance
// ============================================================
// MEM-001 / MEM-008: Memory Services are the only object-access
// boundary; retention/retrieval/lookup/metadata are real and
// verifiable; duplicate/missing/invalid/conflict/failure
// outcomes are distinguished; failure atomicity preserves
// invariants.
// ============================================================

#include <agent_kernel/memory/memory.hpp>
#include <agent_kernel/memory/memory_services.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <vector>

#include "test_doubles.hpp"

namespace ak::memory {
namespace {

TEST(MemoryServices, RetentionAndRetrievalRoundTrip) {
    Memory memory(MakeMemoryIdentity(1));
    ASSERT_TRUE(test::ActivateAndMakeAvailable(memory));
    ASSERT_TRUE(memory.Services()
                    .CreateDomain(MakeMemoryDomainId(1), "knowledge",
                                  test::MakeMetadata("domain"))
                    .IsSuccess());

    MemoryMetadata metadata = test::MakeMetadata("learned", 4);
    metadata.classification = "semantic";
    const auto retained = memory.Services().Retain(
        MakeMemoryEntryId(1), MakeMemoryDomainId(1),
        MemoryObject(MakeMemoryObjectId(1), "fact payload", metadata));
    ASSERT_TRUE(retained.IsSuccess());
    EXPECT_EQ(retained.value, MakeMemoryEntryId(1));

    const auto retrieved = memory.Services().Retrieve(MakeMemoryEntryId(1));
    ASSERT_TRUE(retrieved.IsSuccess());
    EXPECT_EQ(retrieved.value.GetId(), MakeMemoryObjectId(1));
    EXPECT_EQ(retrieved.value.Content(), "fact payload");
    EXPECT_EQ(retrieved.value.GetMetadata(), metadata);
}

TEST(MemoryServices, DomainLookupAndEntryListing) {
    Memory memory(MakeMemoryIdentity(2));
    ASSERT_TRUE(test::ActivateAndMakeAvailable(memory));
    ASSERT_TRUE(memory.Services()
                    .CreateDomain(MakeMemoryDomainId(1), "d1",
                                  test::MakeMetadata("d1"))
                    .IsSuccess());
    ASSERT_TRUE(memory.Services()
                    .CreateDomain(MakeMemoryDomainId(2), "d2",
                                  test::MakeMetadata("d2"))
                    .IsSuccess());

    const auto domain = memory.Services().FindDomain(MakeMemoryDomainId(2));
    ASSERT_TRUE(domain.IsSuccess());
    EXPECT_EQ(domain.value.GetName(), "d2");

    ASSERT_TRUE(memory.Services()
                    .Retain(MakeMemoryEntryId(1), MakeMemoryDomainId(1),
                            MemoryObject(MakeMemoryObjectId(1), "a",
                                         test::MakeMetadata("a")))
                    .IsSuccess());
    ASSERT_TRUE(memory.Services()
                    .Retain(MakeMemoryEntryId(2), MakeMemoryDomainId(1),
                            MemoryObject(MakeMemoryObjectId(2), "b",
                                         test::MakeMetadata("b")))
                    .IsSuccess());
    ASSERT_TRUE(memory.Services()
                    .Retain(MakeMemoryEntryId(3), MakeMemoryDomainId(2),
                            MemoryObject(MakeMemoryObjectId(3), "c",
                                         test::MakeMetadata("c")))
                    .IsSuccess());

    const auto in_domain_1 = memory.Services().ListEntries(MakeMemoryDomainId(1));
    ASSERT_TRUE(in_domain_1.IsSuccess());
    ASSERT_EQ(in_domain_1.value.size(), 2);
    EXPECT_EQ(memory.Services().EntryCount(), 3);
    EXPECT_EQ(memory.Services().DomainCount(), 2);
}

TEST(MemoryServices, ObjectLookupWithoutEntry) {
    Memory memory(MakeMemoryIdentity(3));
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

    const auto object = memory.Services().LookupObject(MakeMemoryObjectId(1));
    ASSERT_TRUE(object.IsSuccess());
    EXPECT_EQ(object.value.Content(), "payload");
}

TEST(MemoryServices, DuplicateIdentitiesAreConflicts) {
    Memory memory(MakeMemoryIdentity(4));
    ASSERT_TRUE(test::ActivateAndMakeAvailable(memory));
    ASSERT_TRUE(memory.Services()
                    .CreateDomain(MakeMemoryDomainId(1), "d",
                                  test::MakeMetadata("d"))
                    .IsSuccess());

    // Duplicate Domain identity -> Conflict.
    const auto duplicate_domain = memory.Services().CreateDomain(
        MakeMemoryDomainId(1), "d-again", test::MakeMetadata("d"));
    EXPECT_EQ(duplicate_domain.status, MemoryResultStatus::kConflict);

    // Duplicate Entry identity -> Conflict.
    const MemoryObject object(MakeMemoryObjectId(1), "payload",
                              test::MakeMetadata("obj"));
    ASSERT_TRUE(memory.Services()
                    .Retain(MakeMemoryEntryId(1), MakeMemoryDomainId(1), object)
                    .IsSuccess());
    const auto duplicate_entry = memory.Services().Retain(
        MakeMemoryEntryId(1), MakeMemoryDomainId(1),
        MemoryObject(MakeMemoryObjectId(2), "other", test::MakeMetadata("other")));
    EXPECT_EQ(duplicate_entry.status, MemoryResultStatus::kConflict);
    EXPECT_EQ(memory.Services().EntryCount(), 1);

    // Duplicate Object identity -> Conflict (no second entry).
    const auto duplicate_object = memory.Services().Retain(
        MakeMemoryEntryId(2), MakeMemoryDomainId(1),
        MemoryObject(MakeMemoryObjectId(1), "again", test::MakeMetadata("again")));
    EXPECT_EQ(duplicate_object.status, MemoryResultStatus::kConflict);
    EXPECT_EQ(memory.Services().EntryCount(), 1);
}

TEST(MemoryServices, MissingAndInvalidInputsAreInvalid) {
    Memory memory(MakeMemoryIdentity(5));
    ASSERT_TRUE(test::ActivateAndMakeAvailable(memory));
    ASSERT_TRUE(memory.Services()
                    .CreateDomain(MakeMemoryDomainId(1), "d",
                                  test::MakeMetadata("d"))
                    .IsSuccess());

    // Missing Domain -> Invalid.
    const auto missing_domain = memory.Services().Retain(
        MakeMemoryEntryId(1), MakeMemoryDomainId(99),
        MemoryObject(MakeMemoryObjectId(1), "payload", test::MakeMetadata("o")));
    EXPECT_EQ(missing_domain.status, MemoryResultStatus::kInvalid);

    // Missing Entry -> Invalid.
    EXPECT_EQ(memory.Services().Retrieve(MakeMemoryEntryId(42)).status,
              MemoryResultStatus::kInvalid);
    EXPECT_EQ(memory.Services().FindEntry(MakeMemoryEntryId(42)).status,
              MemoryResultStatus::kInvalid);
    EXPECT_EQ(memory.Services().GetEntryMetadata(MakeMemoryEntryId(42)).status,
              MemoryResultStatus::kInvalid);

    // Missing Object -> Invalid.
    EXPECT_EQ(memory.Services().LookupObject(MakeMemoryObjectId(42)).status,
              MemoryResultStatus::kInvalid);
    EXPECT_EQ(memory.Services().LookupReference(MakeMemoryObjectId(42)).status,
              MemoryResultStatus::kInvalid);

    // Missing Domain lookup -> Invalid.
    EXPECT_EQ(memory.Services().FindDomain(MakeMemoryDomainId(99)).status,
              MemoryResultStatus::kInvalid);
    EXPECT_EQ(memory.Services().ListEntries(MakeMemoryDomainId(99)).status,
              MemoryResultStatus::kInvalid);

    // Invalid identities -> Invalid.
    const auto invalid_ids = memory.Services().Retain(
        MakeMemoryEntryId(0), MakeMemoryDomainId(0),
        MemoryObject(MakeMemoryObjectId(0), "p", test::MakeMetadata("o")));
    EXPECT_EQ(invalid_ids.status, MemoryResultStatus::kInvalid);
}

TEST(MemoryServices, MetadataHandling) {
    Memory memory(MakeMemoryIdentity(6));
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

    MemoryMetadata updated = test::MakeMetadata("entry", 5);
    updated.retention_policy = "archive";
    const MemoryResult set_result =
        memory.Services().SetEntryMetadata(MakeMemoryEntryId(1), updated);
    EXPECT_TRUE(set_result.IsSuccess());

    const auto read_back = memory.Services().GetEntryMetadata(MakeMemoryEntryId(1));
    ASSERT_TRUE(read_back.IsSuccess());
    EXPECT_EQ(read_back.value, updated);
    EXPECT_EQ(read_back.value.retention_policy, "archive");
}

TEST(MemoryServices, RemoveEntryPreservesObjectInvariant) {
    Memory memory(MakeMemoryIdentity(7));
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

    const MemoryResult removed = memory.Services().RemoveEntry(MakeMemoryEntryId(1));
    EXPECT_TRUE(removed.IsSuccess());
    EXPECT_EQ(memory.Services().EntryCount(), 0);

    // The Object remains retained and retrievable: no dangling
    // reference and no ownership break.
    const auto object = memory.Services().LookupObject(MakeMemoryObjectId(1));
    ASSERT_TRUE(object.IsSuccess());
    EXPECT_EQ(object.value.Content(), "payload");

    // Removing a missing Entry -> Invalid.
    EXPECT_EQ(memory.Services().RemoveEntry(MakeMemoryEntryId(1)).status,
              MemoryResultStatus::kInvalid);
}

TEST(MemoryServices, ProviderFailureProducesNoPartialRegistration) {
    Memory memory(MakeMemoryIdentity(8));
    auto failing = std::make_shared<test::FailingMemoryProvider>(true, true, true);
    (void)memory.SetProvider(failing);
    ASSERT_TRUE(test::ActivateAndMakeAvailable(memory));
    ASSERT_TRUE(memory.Services()
                    .CreateDomain(MakeMemoryDomainId(1), "d",
                                  test::MakeMetadata("d"))
                    .IsSuccess());

    const auto retained = memory.Services().Retain(
        MakeMemoryEntryId(1), MakeMemoryDomainId(1),
        MemoryObject(MakeMemoryObjectId(1), "payload", test::MakeMetadata("obj")));
    EXPECT_EQ(retained.status, MemoryResultStatus::kFailure);

    // Failure atomicity: no partial registration, no dangling
    // reference, and the store is unchanged. The object is not
    // retrievable through any path.
    EXPECT_EQ(memory.Services().EntryCount(), 0);
    EXPECT_FALSE(memory.Services().LookupObject(MakeMemoryObjectId(1)).IsSuccess());
}

}  // namespace
}  // namespace ak::memory