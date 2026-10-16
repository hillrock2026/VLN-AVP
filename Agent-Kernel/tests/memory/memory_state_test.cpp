// ============================================================
// memory_state_test.cpp - P1-IS003 operational-state conformance
// ============================================================
// MEM-005 / MEM-006: Memory exclusively owns operational state;
// all normative operational transitions are validated; invalid
// transitions are rejected; lifecycle and operational state are
// distinct models.
// ============================================================

#include <agent_kernel/memory/memory.hpp>
#include <agent_kernel/memory/memory_operational_state.hpp>
#include <agent_kernel/memory/memory_state.hpp>

#include <gtest/gtest.h>

#include <type_traits>

#include "test_doubles.hpp"

namespace ak::memory {
namespace {

TEST(MemoryState, LifecycleAndOperationalStateAreDistinctModels) {
    static_assert(!std::is_same_v<MemoryLifecycleState, MemoryOperationalState>,
                  "the two state models must remain distinct types");
}

TEST(MemoryState, AllNormativeOperationalTransitionsSucceed) {
    MemoryOperationalStateMachine state;

    // Unavailable -> Ready
    EXPECT_TRUE(state.ToReady().IsSuccess());
    EXPECT_EQ(state.GetState(), MemoryOperationalState::kReady);

    // Ready -> Available
    EXPECT_TRUE(state.ToAvailable().IsSuccess());
    EXPECT_EQ(state.GetState(), MemoryOperationalState::kAvailable);

    // Available -> Busy
    EXPECT_TRUE(state.ToBusy().IsSuccess());
    EXPECT_EQ(state.GetState(), MemoryOperationalState::kBusy);

    // Busy -> Available
    EXPECT_TRUE(state.ToAvailable().IsSuccess());
    EXPECT_EQ(state.GetState(), MemoryOperationalState::kAvailable);

    // Available -> Degraded
    EXPECT_TRUE(state.ToDegraded().IsSuccess());
    EXPECT_EQ(state.GetState(), MemoryOperationalState::kDegraded);

    // Degraded -> Available
    EXPECT_TRUE(state.ToAvailable().IsSuccess());
    EXPECT_EQ(state.GetState(), MemoryOperationalState::kAvailable);

    // Available -> Unavailable
    EXPECT_TRUE(state.ToUnavailable().IsSuccess());
    EXPECT_EQ(state.GetState(), MemoryOperationalState::kUnavailable);

    // Unavailable -> Ready -> Available -> Busy -> Degraded
    ASSERT_TRUE(state.ToReady().IsSuccess());
    ASSERT_TRUE(state.ToAvailable().IsSuccess());
    ASSERT_TRUE(state.ToBusy().IsSuccess());
    EXPECT_TRUE(state.ToDegraded().IsSuccess());
    EXPECT_EQ(state.GetState(), MemoryOperationalState::kDegraded);

    // Degraded -> Unavailable
    EXPECT_TRUE(state.ToUnavailable().IsSuccess());
    EXPECT_EQ(state.GetState(), MemoryOperationalState::kUnavailable);
}

TEST(MemoryState, InvalidOperationalTransitionsAreRejected) {
    MemoryOperationalStateMachine state;

    // Unavailable -> Available is illegal.
    EXPECT_TRUE(state.ToAvailable().IsRejected());
    // Unavailable -> Busy is illegal.
    EXPECT_TRUE(state.ToBusy().IsRejected());
    // Unavailable -> Degraded is illegal.
    EXPECT_TRUE(state.ToDegraded().IsRejected());
    EXPECT_EQ(state.GetState(), MemoryOperationalState::kUnavailable);

    // Ready -> Busy is illegal.
    ASSERT_TRUE(state.ToReady().IsSuccess());
    EXPECT_TRUE(state.ToBusy().IsRejected());
    // Ready -> Degraded is illegal.
    EXPECT_TRUE(state.ToDegraded().IsRejected());
    // Ready -> Unavailable is illegal.
    EXPECT_TRUE(state.ToUnavailable().IsRejected());
    EXPECT_EQ(state.GetState(), MemoryOperationalState::kReady);

    // Busy -> Unavailable is illegal.
    ASSERT_TRUE(state.ToAvailable().IsSuccess());
    ASSERT_TRUE(state.ToBusy().IsSuccess());
    EXPECT_TRUE(state.ToUnavailable().IsRejected());
    EXPECT_EQ(state.GetState(), MemoryOperationalState::kBusy);

    // Degraded -> Busy is illegal.
    ASSERT_TRUE(state.ToDegraded().IsSuccess());
    EXPECT_TRUE(state.ToBusy().IsRejected());
    // Degraded -> Ready is illegal.
    EXPECT_TRUE(state.ToReady().IsRejected());
    EXPECT_EQ(state.GetState(), MemoryOperationalState::kDegraded);
}

TEST(MemoryState, MemoryRootOwnsOperationalStateManagement) {
    Memory memory(MakeMemoryIdentity(1));
    EXPECT_EQ(memory.GetOperationalState(), MemoryOperationalState::kUnavailable);

    EXPECT_TRUE(memory.MarkReady().IsSuccess());
    EXPECT_TRUE(memory.MarkAvailable().IsSuccess());
    EXPECT_TRUE(memory.MarkBusy().IsSuccess());
    EXPECT_TRUE(memory.MarkDegraded().IsSuccess());
    EXPECT_EQ(memory.GetOperationalState(), MemoryOperationalState::kDegraded);

    EXPECT_TRUE(memory.MarkAvailable().IsSuccess());
    EXPECT_TRUE(memory.MarkUnavailable().IsSuccess());
    EXPECT_EQ(memory.GetOperationalState(), MemoryOperationalState::kUnavailable);
}

TEST(MemoryState, AvailabilityContractIsRespected) {
    Memory memory(MakeMemoryIdentity(2));
    ASSERT_TRUE(memory.InitializeLifecycle().IsSuccess());
    ASSERT_TRUE(memory.CompleteInitialization().IsSuccess());

    const MemoryDomainId domain = MakeMemoryDomainId(1);
    const MemoryObject object(MakeMemoryObjectId(1), "payload",
                              test::MakeMetadata("obj"));

    // Establish the Domain through the Memory Service boundary
    // while fully available.
    ASSERT_TRUE(memory.MarkReady().IsSuccess());
    ASSERT_TRUE(memory.MarkAvailable().IsSuccess());
    ASSERT_TRUE(memory.Services()
                    .CreateDomain(domain, "d", test::MakeMetadata("d"))
                    .IsSuccess());

    // Unavailable: not available.
    ASSERT_TRUE(memory.MarkUnavailable().IsSuccess());
    MemoryResultValue<MemoryEntryId> result =
        memory.Services().Retain(MakeMemoryEntryId(1), domain, object);
    EXPECT_EQ(result.status, MemoryResultStatus::kUnavailable);

    // Ready: preparation only - normal operations unavailable.
    ASSERT_TRUE(memory.MarkReady().IsSuccess());
    result = memory.Services().Retain(MakeMemoryEntryId(1), domain, object);
    EXPECT_EQ(result.status, MemoryResultStatus::kUnavailable);

    // Available: fully available.
    ASSERT_TRUE(memory.MarkAvailable().IsSuccess());
    result = memory.Services().Retain(MakeMemoryEntryId(1), domain, object);
    EXPECT_TRUE(result.IsSuccess());

    // Busy: available while preserving consistency.
    ASSERT_TRUE(memory.MarkBusy().IsSuccess());
    const MemoryObject object2(MakeMemoryObjectId(2), "payload-2",
                               test::MakeMetadata("obj-2"));
    result = memory.Services().Retain(MakeMemoryEntryId(2), domain, object2);
    EXPECT_TRUE(result.IsSuccess());
    EXPECT_EQ(memory.Services().EntryCount(), 2);

    // Degraded: reduced but contract-preserving availability.
    ASSERT_TRUE(memory.MarkDegraded().IsSuccess());
    result = memory.Services().Retain(MakeMemoryEntryId(3), domain, object2);
    EXPECT_EQ(result.status, MemoryResultStatus::kConflict);  // duplicate object
}
TEST(MemoryState, FoundationValidatorOnlyValidates) {
    const ak::TransitionResult legal = ValidateMemoryOperationalTransition(
        MemoryOperationalState::kUnavailable, MemoryOperationalState::kReady);
    EXPECT_TRUE(legal.Accepted());

    const ak::TransitionResult illegal = ValidateMemoryOperationalTransition(
        MemoryOperationalState::kUnavailable, MemoryOperationalState::kAvailable);
    EXPECT_TRUE(illegal.Rejected());

    MemoryOperationalStateMachine state;
    (void)ValidateMemoryOperationalTransition(
        MemoryOperationalState::kUnavailable, MemoryOperationalState::kReady);
    EXPECT_EQ(state.GetState(), MemoryOperationalState::kUnavailable);
}

}  // namespace
}  // namespace ak::memory