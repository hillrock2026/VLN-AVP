// ============================================================
// context_lifecycle_test.cpp - P1-IS004 lifecycle conformance
// ============================================================
// CTX-003 / CTX-006: Context owns the lifecycle of every
// Context Object; all normative transitions are validated;
// invalid and terminal behavior is enforced; lifecycle remains
// independent from operational state and from every other
// subsystem lifecycle.
// ============================================================

#include <agent_kernel/context/context.hpp>
#include <agent_kernel/context/context_lifecycle.hpp>
#include <agent_kernel/context/context_state.hpp>

#include <gtest/gtest.h>

#include <string>
#include <type_traits>

#include "test_doubles.hpp"

namespace ak::context {
namespace {

TEST(ContextLifecycle, AllNormativeTransitionsSucceed) {
    ContextLifecycle lifecycle;

    // Created -> Initialized
    EXPECT_TRUE(lifecycle.Initialize().IsSuccess());
    EXPECT_EQ(lifecycle.GetState(), ContextLifecycleState::kInitialized);

    // Initialized -> Active
    EXPECT_TRUE(lifecycle.Activate().IsSuccess());
    EXPECT_EQ(lifecycle.GetState(), ContextLifecycleState::kActive);

    // Active -> Updated
    EXPECT_TRUE(lifecycle.BeginUpdate().IsSuccess());
    EXPECT_EQ(lifecycle.GetState(), ContextLifecycleState::kUpdated);

    // Updated -> Active
    EXPECT_TRUE(lifecycle.CompleteUpdate().IsSuccess());
    EXPECT_EQ(lifecycle.GetState(), ContextLifecycleState::kActive);

    // Active -> Released (terminal)
    EXPECT_TRUE(lifecycle.Release().IsSuccess());
    EXPECT_EQ(lifecycle.GetState(), ContextLifecycleState::kReleased);
}

TEST(ContextLifecycle, UpdatedToReleasedIsNormative) {
    ContextLifecycle lifecycle;
    ASSERT_TRUE(lifecycle.Initialize().IsSuccess());
    ASSERT_TRUE(lifecycle.Activate().IsSuccess());
    ASSERT_TRUE(lifecycle.BeginUpdate().IsSuccess());
    EXPECT_EQ(lifecycle.GetState(), ContextLifecycleState::kUpdated);

    // Updated -> Released is a permitted lifecycle transition.
    EXPECT_TRUE(lifecycle.Release().IsSuccess());
    EXPECT_EQ(lifecycle.GetState(), ContextLifecycleState::kReleased);
}

TEST(ContextLifecycle, InvalidTransitionsAreRejectedWithoutPartialChange) {
    ContextLifecycle lifecycle;

    // Created -> Active is illegal.
    EXPECT_TRUE(lifecycle.Activate().IsRejected());
    EXPECT_EQ(lifecycle.GetState(), ContextLifecycleState::kCreated);

    // Initialized -> Updated is illegal.
    ASSERT_TRUE(lifecycle.Initialize().IsSuccess());
    EXPECT_TRUE(lifecycle.BeginUpdate().IsRejected());
    EXPECT_EQ(lifecycle.GetState(), ContextLifecycleState::kInitialized);

    // Active -> Initialized (reverse) is illegal.
    ASSERT_TRUE(lifecycle.Activate().IsSuccess());
    EXPECT_TRUE(lifecycle.Initialize().IsRejected());
    EXPECT_EQ(lifecycle.GetState(), ContextLifecycleState::kActive);

    // Self/illegal transitions from Active are illegal.
    EXPECT_TRUE(lifecycle.Activate().IsRejected());
    EXPECT_TRUE(lifecycle.CompleteUpdate().IsRejected());
}

TEST(ContextLifecycle, ReleasedIsTerminal) {
    ContextLifecycle lifecycle;
    ASSERT_TRUE(lifecycle.Initialize().IsSuccess());
    ASSERT_TRUE(lifecycle.Activate().IsSuccess());
    ASSERT_TRUE(lifecycle.Release().IsSuccess());

    EXPECT_TRUE(lifecycle.Initialize().IsRejected());
    EXPECT_TRUE(lifecycle.Activate().IsRejected());
    EXPECT_TRUE(lifecycle.BeginUpdate().IsRejected());
    EXPECT_TRUE(lifecycle.CompleteUpdate().IsRejected());
    EXPECT_TRUE(lifecycle.Release().IsRejected());
    EXPECT_EQ(lifecycle.GetState(), ContextLifecycleState::kReleased);
}

TEST(ContextLifecycle, LifecycleDoesNotMutateOperationalState) {
    // Lifecycle is an independent dimension: moving lifecycle
    // never rewrites the operational-state machine.
    Context context(MakeContextIdentity(1));
    const ContextObjectId object_id = MakeContextObjectId(1);
    ASSERT_TRUE(context.Creation()
                    .CreateObject(object_id, "working_state", "payload",
                                  test::MakeMetadata("obj"))
                    .IsSuccess());

    auto view = context.Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_EQ(view.value.lifecycle, ContextLifecycleState::kCreated);
    EXPECT_EQ(view.value.operational, ContextOperationalState::kUninitialized);

    ASSERT_TRUE(context.Creation().InitializeObject(object_id).IsSuccess());
    ASSERT_TRUE(context.Creation().ActivateObject(object_id).IsSuccess());

    view = context.Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_EQ(view.value.lifecycle, ContextLifecycleState::kActive);
    EXPECT_EQ(view.value.operational, ContextOperationalState::kActive);
}

TEST(ContextLifecycle, FoundationValidatorOnlyValidates) {
    const ak::TransitionResult legal = ValidateContextLifecycleTransition(
        ContextLifecycleState::kCreated, ContextLifecycleState::kInitialized);
    EXPECT_TRUE(legal.Accepted());

    const ak::TransitionResult illegal = ValidateContextLifecycleTransition(
        ContextLifecycleState::kReleased, ContextLifecycleState::kActive);
    EXPECT_TRUE(illegal.Rejected());

    // The Foundation validator cannot initiate transitions: a
    // standalone lifecycle machine is unchanged by validation.
    ContextLifecycle lifecycle;
    (void)ValidateContextLifecycleTransition(ContextLifecycleState::kCreated,
                                             ContextLifecycleState::kInitialized);
    EXPECT_EQ(lifecycle.GetState(), ContextLifecycleState::kCreated);
}

TEST(ContextLifecycle, LifecycleIsContextOwnedAndIndependent) {
    // The lifecycle machine references no Agent, Memory, Planner,
    // Tool, Session, Workflow, Task, or Runtime type: it is a
    // Context-owned representation with its own transition rule.
    static_assert(!std::is_same_v<ContextLifecycleState,
                                  ContextOperationalState>);
    EXPECT_TRUE(IsLegalContextLifecycleTransition(
        ContextLifecycleState::kActive, ContextLifecycleState::kUpdated));
    EXPECT_FALSE(IsLegalContextLifecycleTransition(
        ContextLifecycleState::kReleased, ContextLifecycleState::kActive));
}

}  // namespace
}  // namespace ak::context


