// ============================================================
// foundation_reuse_test.cpp - P1-IS003 Foundation conformance
// ============================================================
// MEM-014: Memory reuses P1-IS001 Foundation mechanisms
// (identity, lifecycle validation, registries, diagnostics,
// metadata) while Foundation remains neutral; Foundation never
// owns Memory lifecycle, state, services, or providers.
// ============================================================

#include <agent_kernel/foundation/kernel_diagnostics.hpp>
#include <agent_kernel/foundation/kernel_identity.hpp>
#include <agent_kernel/foundation/kernel_lifecycle.hpp>
#include <agent_kernel/foundation/kernel_metadata.hpp>
#include <agent_kernel/foundation/kernel_registry.hpp>
#include <agent_kernel/memory/memory.hpp>
#include <agent_kernel/memory/memory_identity.hpp>
#include <agent_kernel/memory/memory_state.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <memory>
#include <type_traits>
#include <utility>

#include "test_doubles.hpp"

namespace ak::memory {
namespace {

TEST(MemoryFoundationReuse, FoundationIdentityMechanicsAreReused) {
    // Memory identity is a Foundation typed identity value; the
    // Foundation supplies mechanics only.
    static_assert(std::is_base_of_v<ak::KernelIdentity, MemoryIdentity>);
    static_assert(std::is_base_of_v<ak::KernelIdentity, MemoryDomainId>);

    const MemoryIdentity identity = MakeMemoryIdentity(9);
    EXPECT_TRUE(identity.IsValid());
    EXPECT_EQ(identity.Value(), 9);
}

TEST(MemoryFoundationReuse, FoundationLifecycleMechanicsAreReusedButNeutral) {
    // The Foundation validator is reused for validation; it is
    // not the lifecycle authority: it cannot change Memory.
    ak::LifecycleTransitionValidator validator(&MemoryLifecycleTransitionRule);
    EXPECT_TRUE(validator
                    .Validate(ToLifecycleState(MemoryLifecycleState::kRegistered),
                              ToLifecycleState(MemoryLifecycleState::kInitializing))
                    .Accepted());
    EXPECT_TRUE(validator
                    .Validate(ToLifecycleState(MemoryLifecycleState::kDisposed),
                              ToLifecycleState(MemoryLifecycleState::kActive))
                    .Rejected());

    Memory memory(MakeMemoryIdentity(1));
    EXPECT_EQ(memory.GetLifecycleState(), MemoryLifecycleState::kRegistered);
}

TEST(MemoryFoundationReuse, FoundationMetadataAndDiagnosticsAreReused) {
    ak::KernelMetadata neutral;
    neutral.name = "memory-config";
    Memory memory(MakeMemoryIdentity(2));
    memory.SetConfiguration(neutral);
    EXPECT_EQ(memory.GetConfiguration().name, "memory-config");

    ak::DiagnosticSink sink;
    sink.Add(ak::DiagnosticSeverity::kInfo, 1, "info");
    EXPECT_EQ(sink.Count(), 1);
    EXPECT_FALSE(sink.HasErrors());
}

TEST(MemoryFoundationReuse, RegistryMechanicsServeMemoryOwnership) {
    // Foundation registry mechanics are reused inside the Memory
    // store; containment does not transfer ownership to the
    // Foundation, and Memory semantics (duplicate rejection)
    // remain Memory-owned.
    ak::OwnerScopedRegistry<MemoryObjectId, MemoryObject> objects;
    objects.Register(MakeMemoryObjectId(1),
                     std::make_unique<MemoryObject>(
                         MakeMemoryObjectId(1), "payload",
                         test::MakeMetadata("obj")));
    EXPECT_TRUE(objects.Contains(MakeMemoryObjectId(1)));
    EXPECT_EQ(objects.Count(), 1);

    // Memory-owned duplicate semantics are enforced by Memory
    // Services (Conflict), not by the registry overwriting.
    Memory memory(MakeMemoryIdentity(3));
    ASSERT_TRUE(test::ActivateAndMakeAvailable(memory));
    ASSERT_TRUE(memory.Services()
                    .CreateDomain(MakeMemoryDomainId(1), "d",
                                  test::MakeMetadata("d"))
                    .IsSuccess());
    ASSERT_TRUE(memory.Services()
                    .Retain(MakeMemoryEntryId(1), MakeMemoryDomainId(1),
                            MemoryObject(MakeMemoryObjectId(1), "a",
                                         test::MakeMetadata("a")))
                    .IsSuccess());
    const auto duplicate = memory.Services().Retain(
        MakeMemoryEntryId(2), MakeMemoryDomainId(1),
        MemoryObject(MakeMemoryObjectId(1), "b", test::MakeMetadata("b")));
    EXPECT_EQ(duplicate.status, MemoryResultStatus::kConflict);
}

TEST(MemoryFoundationReuse, FoundationDoesNotOwnMemorySemantics) {
    // Foundation value types carry no Memory semantics: the same
    // neutral metadata is Memory-agnostic.
    ak::KernelMetadata neutral;
    neutral.name = "neutral";
    MemoryMetadata memory_metadata;
    memory_metadata.core = neutral;
    memory_metadata.version = 2;

    EXPECT_EQ(memory_metadata.core.name, "neutral");
    EXPECT_EQ(memory_metadata.version, 2);
}

}  // namespace
}  // namespace ak::memory