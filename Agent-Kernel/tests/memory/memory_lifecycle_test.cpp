// ============================================================
// memory_lifecycle_test.cpp - P1-IS003 lifecycle conformance
// ============================================================
// MEM-003 / MEM-006: Memory owns its lifecycle; all normative
// transitions are validated; invalid and terminal behavior is
// enforced; services are unavailable before Active; lifecycle
// and operational state remain separate.
// ============================================================

#include <agent_kernel/memory/memory.hpp>
#include <agent_kernel/memory/memory_lifecycle.hpp>
#include <agent_kernel/memory/memory_state.hpp>

#include <gtest/gtest.h>

#include <string>

#include "test_doubles.hpp"

namespace ak::memory {
namespace {

TEST(MemoryLifecycle, AllNormativeTransitionsSucceed) {
    Memory memory(MakeMemoryIdentity(1));

    // Registered -> Initializing
    EXPECT_TRUE(memory.InitializeLifecycle().IsSuccess());
    EXPECT_EQ(memory.GetLifecycleState(), MemoryLifecycleState::kInitializing);

    // Initializing -> Active
    EXPECT_TRUE(memory.CompleteInitialization().IsSuccess());
    EXPECT_EQ(memory.GetLifecycleState(), MemoryLifecycleState::kActive);

    // Active -> Suspended
    EXPECT_TRUE(memory.Suspend().IsSuccess());
    EXPECT_EQ(memory.GetLifecycleState(), MemoryLifecycleState::kSuspended);

    // Suspended -> Active
    EXPECT_TRUE(memory.Resume().IsSuccess());
    EXPECT_EQ(memory.GetLifecycleState(), MemoryLifecycleState::kActive);

    // Active -> Terminating
    EXPECT_TRUE(memory.Terminate().IsSuccess());
    EXPECT_EQ(memory.GetLifecycleState(), MemoryLifecycleState::kTerminating);

    // Terminating -> Disposed
    EXPECT_TRUE(memory.Dispose().IsSuccess());
    EXPECT_EQ(memory.GetLifecycleState(), MemoryLifecycleState::kDisposed);
}

TEST(MemoryLifecycle, SuspendedPathViaTerminatingAlsoValid) {
    Memory memory(MakeMemoryIdentity(2));
    ASSERT_TRUE(memory.InitializeLifecycle().IsSuccess());
    ASSERT_TRUE(memory.CompleteInitialization().IsSuccess());
    ASSERT_TRUE(memory.Suspend().IsSuccess());

    // Suspended -> Terminating is normative.
    EXPECT_TRUE(memory.Terminate().IsSuccess());
    EXPECT_EQ(memory.GetLifecycleState(), MemoryLifecycleState::kTerminating);
}

TEST(MemoryLifecycle, InvalidTransitionsAreRejectedWithoutPartialChange) {
    Memory memory(MakeMemoryIdentity(3));

    // Registered -> Active is illegal.
    const MemoryResult jump = memory.CompleteInitialization();
    EXPECT_FALSE(jump.IsSuccess());
    EXPECT_EQ(jump.status, MemoryResultStatus::kRejected);
    EXPECT_EQ(memory.GetLifecycleState(), MemoryLifecycleState::kRegistered);

    // Initializing -> Suspended is illegal.
    ASSERT_TRUE(memory.InitializeLifecycle().IsSuccess());
    EXPECT_TRUE(memory.Suspend().IsRejected());
    EXPECT_EQ(memory.GetLifecycleState(), MemoryLifecycleState::kInitializing);

    // Active -> Disposed is illegal (Terminating required).
    ASSERT_TRUE(memory.CompleteInitialization().IsSuccess());
    EXPECT_TRUE(memory.Dispose().IsRejected());
    EXPECT_EQ(memory.GetLifecycleState(), MemoryLifecycleState::kActive);

    // Suspended -> Suspended (self) is illegal.
    ASSERT_TRUE(memory.Suspend().IsSuccess());
    EXPECT_TRUE(memory.Suspend().IsRejected());
    EXPECT_EQ(memory.GetLifecycleState(), MemoryLifecycleState::kSuspended);
}

TEST(MemoryLifecycle, DisposedIsTerminal) {
    Memory memory(MakeMemoryIdentity(4));
    ASSERT_TRUE(memory.InitializeLifecycle().IsSuccess());
    ASSERT_TRUE(memory.CompleteInitialization().IsSuccess());
    ASSERT_TRUE(memory.Terminate().IsSuccess());
    ASSERT_TRUE(memory.Dispose().IsSuccess());

    EXPECT_TRUE(memory.InitializeLifecycle().IsRejected());
    EXPECT_TRUE(memory.CompleteInitialization().IsRejected());
    EXPECT_TRUE(memory.Resume().IsRejected());
    EXPECT_TRUE(memory.Suspend().IsRejected());
    EXPECT_TRUE(memory.Terminate().IsRejected());
    EXPECT_TRUE(memory.Dispose().IsRejected());
    EXPECT_EQ(memory.GetLifecycleState(), MemoryLifecycleState::kDisposed);
}

TEST(MemoryLifecycle, ServicesUnavailableBeforeActive) {
    Memory memory(MakeMemoryIdentity(5));
    const MemoryObject object(MakeMemoryObjectId(1), "payload",
                              test::MakeMetadata("obj"));

    // Registered: rejected (lifecycle gate).
    MemoryResultValue<MemoryEntryId> result = memory.Services().Retain(
        MakeMemoryEntryId(1), MakeMemoryDomainId(1), object);
    EXPECT_EQ(result.status, MemoryResultStatus::kRejected);
    EXPECT_EQ(memory.Services().EntryCount(), 0);

    // Initializing: still rejected.
    ASSERT_TRUE(memory.InitializeLifecycle().IsSuccess());
    result = memory.Services().Retain(MakeMemoryEntryId(1),
                                      MakeMemoryDomainId(1), object);
    EXPECT_EQ(result.status, MemoryResultStatus::kRejected);

    // Active: lifecycle gate opens (operational gate still
    // requires availability).
    ASSERT_TRUE(memory.CompleteInitialization().IsSuccess());
    result = memory.Services().Retain(MakeMemoryEntryId(1),
                                      MakeMemoryDomainId(1), object);
    EXPECT_EQ(result.status, MemoryResultStatus::kUnavailable);
}

TEST(MemoryLifecycle, LifecycleTransitionsDoNotMutateOperationalState) {
    Memory memory(MakeMemoryIdentity(6));
    ASSERT_EQ(memory.GetOperationalState(), MemoryOperationalState::kUnavailable);

    ASSERT_TRUE(memory.InitializeLifecycle().IsSuccess());
    ASSERT_TRUE(memory.CompleteInitialization().IsSuccess());
    ASSERT_TRUE(memory.Suspend().IsSuccess());
    ASSERT_TRUE(memory.Resume().IsSuccess());
    ASSERT_TRUE(memory.Terminate().IsSuccess());
    ASSERT_TRUE(memory.Dispose().IsSuccess());

    // Operational state is a separate model: lifecycle movement
    // never rewrites it.
    EXPECT_EQ(memory.GetOperationalState(), MemoryOperationalState::kUnavailable);
}

TEST(MemoryLifecycle, FoundationValidatorOnlyValidates) {
    // The Foundation validator reports legality but cannot
    // initiate transitions: repeated validation is stateless and
    // no Memory object changes.
    const ak::TransitionResult legal = ValidateMemoryLifecycleTransition(
        MemoryLifecycleState::kRegistered, MemoryLifecycleState::kInitializing);
    EXPECT_TRUE(legal.Accepted());

    const ak::TransitionResult illegal = ValidateMemoryLifecycleTransition(
        MemoryLifecycleState::kActive, MemoryLifecycleState::kDisposed);
    EXPECT_TRUE(illegal.Rejected());

    Memory memory(MakeMemoryIdentity(7));
    ASSERT_EQ(memory.GetLifecycleState(), MemoryLifecycleState::kRegistered);
    (void)ValidateMemoryLifecycleTransition(MemoryLifecycleState::kRegistered,
                                            MemoryLifecycleState::kInitializing);
    EXPECT_EQ(memory.GetLifecycleState(), MemoryLifecycleState::kRegistered);
}

}  // namespace
}  // namespace ak::memory