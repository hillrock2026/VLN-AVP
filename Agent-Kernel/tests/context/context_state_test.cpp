// ============================================================
// context_state_test.cpp - P1-IS004 operational-state conformance
// ============================================================
// CTX-005 / CTX-006: Context owns operational state; all
// normative transitions are validated; invalid and terminal
// behavior is enforced; state remains distinct from lifecycle
// and independent of Runtime state.
// ============================================================

#include <agent_kernel/context/context.hpp>
#include <agent_kernel/context/context_boundary_validator.hpp>
#include <agent_kernel/context/context_operational_state.hpp>
#include <agent_kernel/context/context_state.hpp>

#include <gtest/gtest.h>

#include <string>
#include <type_traits>

#include "test_doubles.hpp"

namespace ak::context {
namespace {

TEST(ContextState, AllNormativeTransitionsSucceed) {
    ContextOperationalStateMachine operational;

    // Uninitialized -> Ready
    EXPECT_TRUE(operational.ToReady().IsSuccess());
    EXPECT_EQ(operational.GetState(), ContextOperationalState::kReady);

    // Ready -> Active
    EXPECT_TRUE(operational.ToActive().IsSuccess());
    EXPECT_EQ(operational.GetState(), ContextOperationalState::kActive);

    // Active -> Updating
    EXPECT_TRUE(operational.ToUpdating().IsSuccess());
    EXPECT_EQ(operational.GetState(), ContextOperationalState::kUpdating);

    // Updating -> Active
    EXPECT_TRUE(operational.ToActiveAfterUpdate().IsSuccess());
    EXPECT_EQ(operational.GetState(), ContextOperationalState::kActive);

    // Active -> Released (terminal)
    EXPECT_TRUE(operational.ToReleased().IsSuccess());
    EXPECT_EQ(operational.GetState(), ContextOperationalState::kReleased);
}

TEST(ContextState, InvalidTransitionsAreRejectedWithoutPartialChange) {
    ContextOperationalStateMachine operational;

    // Uninitialized -> Active is illegal.
    EXPECT_TRUE(operational.ToActive().IsRejected());
    EXPECT_EQ(operational.GetState(), ContextOperationalState::kUninitialized);

    // Ready -> Updating is illegal.
    ASSERT_TRUE(operational.ToReady().IsSuccess());
    EXPECT_TRUE(operational.ToUpdating().IsRejected());
    EXPECT_EQ(operational.GetState(), ContextOperationalState::kReady);

    // Active -> Ready (reverse) is illegal.
    ASSERT_TRUE(operational.ToActive().IsSuccess());
    EXPECT_TRUE(operational.ToReady().IsRejected());
    EXPECT_EQ(operational.GetState(), ContextOperationalState::kActive);

    // Updating -> Released is NOT normative (must return to
    // Active first).
    ASSERT_TRUE(operational.ToUpdating().IsSuccess());
    EXPECT_TRUE(operational.ToReleased().IsRejected());
    EXPECT_EQ(operational.GetState(), ContextOperationalState::kUpdating);
}

TEST(ContextState, ReleasedIsTerminal) {
    ContextOperationalStateMachine operational;
    ASSERT_TRUE(operational.ToReady().IsSuccess());
    ASSERT_TRUE(operational.ToActive().IsSuccess());
    ASSERT_TRUE(operational.ToReleased().IsSuccess());

    EXPECT_TRUE(operational.ToReady().IsRejected());
    EXPECT_TRUE(operational.ToActive().IsRejected());
    EXPECT_TRUE(operational.ToUpdating().IsRejected());
    EXPECT_TRUE(operational.ToActiveAfterUpdate().IsRejected());
    EXPECT_TRUE(operational.ToReleased().IsRejected());
    EXPECT_EQ(operational.GetState(), ContextOperationalState::kReleased);
}

TEST(ContextState, StateIsDistinctFromLifecycle) {
    // Distinct types at compile time.
    static_assert(!std::is_same_v<ContextLifecycleState,
                                  ContextOperationalState>);
    static_assert(!std::is_same_v<ContextLifecycle, ContextOperationalStateMachine>);

    // Distinct normative rules: lifecycle allows Updated -> Released
    // while operational requires Updating -> Active.
    EXPECT_TRUE(IsLegalContextLifecycleTransition(
        ContextLifecycleState::kUpdated, ContextLifecycleState::kReleased));
    EXPECT_FALSE(IsLegalContextOperationalTransition(
        ContextOperationalState::kUpdating, ContextOperationalState::kReleased));

    // An operational machine is never rewritten by lifecycle
    // validation: the two dimensions are independent.
    ContextOperationalStateMachine operational;
    (void)ValidateContextOperationalTransition(
        ContextOperationalState::kUninitialized, ContextOperationalState::kReady);
    EXPECT_EQ(operational.GetState(), ContextOperationalState::kUninitialized);
}

TEST(ContextState, ServiceDrivesBothDimensionsInLockstep) {
    // Through the service boundary, lifecycle and operational
    // state move together while remaining independently readable.
    Context context(MakeContextIdentity(1));
    const ContextObjectId object_id = MakeContextObjectId(1);
    ASSERT_TRUE(context.Creation()
                    .CreateObject(object_id, "working_state", "payload",
                                  test::MakeMetadata("obj"))
                    .IsSuccess());
    ASSERT_TRUE(context.Creation().InitializeObject(object_id).IsSuccess());

    auto view = context.Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_EQ(view.value.lifecycle, ContextLifecycleState::kInitialized);
    EXPECT_EQ(view.value.operational, ContextOperationalState::kReady);

    ASSERT_TRUE(context.Creation().ActivateObject(object_id).IsSuccess());
    ASSERT_TRUE(context.Update().BeginUpdate(object_id).IsSuccess());

    view = context.Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_EQ(view.value.lifecycle, ContextLifecycleState::kUpdated);
    EXPECT_EQ(view.value.operational, ContextOperationalState::kUpdating);

    ASSERT_TRUE(context.Update().CompleteUpdate(object_id).IsSuccess());
    view = context.Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_EQ(view.value.lifecycle, ContextLifecycleState::kActive);
    EXPECT_EQ(view.value.operational, ContextOperationalState::kActive);
}

TEST(ContextState, OperationalStateIsIndependentOfRuntime) {
    // Phase 2: no Runtime state exists or is referenced; the
    // Context operational model is self-contained.
    static_assert(ContextBoundaryValidator::Phase2HasNoConcreteRuntimeDependency());
    ContextOperationalStateMachine operational;
    EXPECT_EQ(operational.GetStateName(), "Uninitialized");
}

}  // namespace
}  // namespace ak::context

