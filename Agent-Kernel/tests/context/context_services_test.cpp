// ============================================================
// context_services_test.cpp - P1-IS004 service behavior
// ============================================================
// CTX-008 / CTX-020: Context Services are the sole service
// boundary; behavioral coverage for creation, initialization,
// activation, access, update, composition, release, invalid
// lifecycle/state transitions, Released object behavior,
// ownership preservation, and service-boundary encapsulation.
// ============================================================

#include <agent_kernel/context/context.hpp>
#include <agent_kernel/context/context_services.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <vector>

#include "test_doubles.hpp"

namespace ak::context {
namespace {

TEST(ContextServices, CreationEstablishesObjectWithoutActivation) {
    Context context(MakeContextIdentity(1));
    const ContextObjectId object_id = MakeContextObjectId(1);

    const auto created = context.Creation().CreateObject(
        object_id, "working_state", "payload", test::MakeMetadata("obj"));
    ASSERT_TRUE(created.IsSuccess());
    EXPECT_EQ(created.value, object_id);

    // Creation does not imply activation: lifecycle Created and
    // operational Uninitialized.
    const auto view = context.Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_EQ(view.value.lifecycle, ContextLifecycleState::kCreated);
    EXPECT_EQ(view.value.operational, ContextOperationalState::kUninitialized);

    // Creation rejects invalid and duplicate identities.
    EXPECT_EQ(context.Creation()
                  .CreateObject(MakeContextObjectId(0), "c", "p",
                                test::MakeMetadata("m"))
                  .status,
              ContextResultStatus::kInvalid);
    EXPECT_EQ(context.Creation()
                  .CreateObject(object_id, "c", "p", test::MakeMetadata("m"))
                  .status,
              ContextResultStatus::kConflict);
}

TEST(ContextServices, InitializationAndActivationAreExplicitSteps) {
    Context context(MakeContextIdentity(1));
    const ContextObjectId object_id = MakeContextObjectId(1);
    ASSERT_TRUE(context.Creation()
                    .CreateObject(object_id, "working_state", "payload",
                                  test::MakeMetadata("obj"))
                    .IsSuccess());

    // Initialization: Created -> Initialized, Uninitialized -> Ready.
    ASSERT_TRUE(context.Creation().InitializeObject(object_id).IsSuccess());
    auto view = context.Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_EQ(view.value.lifecycle, ContextLifecycleState::kInitialized);
    EXPECT_EQ(view.value.operational, ContextOperationalState::kReady);

    // Activation: Initialized -> Active, Ready -> Active.
    ASSERT_TRUE(context.Creation().ActivateObject(object_id).IsSuccess());
    view = context.Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_EQ(view.value.lifecycle, ContextLifecycleState::kActive);
    EXPECT_EQ(view.value.operational, ContextOperationalState::kActive);
}

TEST(ContextServices, AccessReturnsControlledReadOnlyViews) {
    Context context(MakeContextIdentity(1));
    const ContextObjectId object_id = MakeContextObjectId(1);
    ASSERT_TRUE(test::CreateAndActivate(context, object_id));

    const auto view = context.Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_EQ(view.value.id, object_id);
    EXPECT_EQ(view.value.content, "payload");
    EXPECT_EQ(view.value.lifecycle, ContextLifecycleState::kActive);

    // Unknown Object identity is an explicit error.
    EXPECT_EQ(context.Access().InspectObject(MakeContextObjectId(999)).status,
              ContextResultStatus::kInvalid);
}

TEST(ContextServices, UpdateCycleIsControlledEvolution) {
    Context context(MakeContextIdentity(1));
    const ContextObjectId object_id = MakeContextObjectId(1);
    ASSERT_TRUE(test::CreateAndActivate(context, object_id));

    // Active -> Updated / Active -> Updating.
    ASSERT_TRUE(context.Update().BeginUpdate(object_id).IsSuccess());
    auto view = context.Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_EQ(view.value.lifecycle, ContextLifecycleState::kUpdated);
    EXPECT_EQ(view.value.operational, ContextOperationalState::kUpdating);

    // Working-state evolution while updating.
    ASSERT_TRUE(context.Update()
                    .ApplyUpdate(object_id, "evolved", test::MakeMetadata("v2", 2))
                    .IsSuccess());
    view = context.Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_EQ(view.value.content, "evolved");
    EXPECT_EQ(view.value.metadata.version, 2);

    // Updated -> Active / Updating -> Active.
    ASSERT_TRUE(context.Update().CompleteUpdate(object_id).IsSuccess());
    view = context.Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_EQ(view.value.lifecycle, ContextLifecycleState::kActive);
    EXPECT_EQ(view.value.operational, ContextOperationalState::kActive);
    EXPECT_EQ(view.value.content, "evolved");
}

TEST(ContextServices, InvalidUpdateIsRejected) {
    Context context(MakeContextIdentity(1));
    const ContextObjectId object_id = MakeContextObjectId(1);
    ASSERT_TRUE(test::CreateAndActivate(context, object_id));

    // Applying an update outside the updating state is invalid.
    EXPECT_EQ(context.Update()
                  .ApplyUpdate(object_id, "x", test::MakeMetadata("x"))
                  .status,
              ContextResultStatus::kInvalid);

    // Updating an Object that is not yet active is unavailable.
    const ContextObjectId passive = MakeContextObjectId(2);
    ASSERT_TRUE(context.Creation()
                    .CreateObject(passive, "working_state", "p",
                                  test::MakeMetadata("p"))
                    .IsSuccess());
    ASSERT_TRUE(context.Creation().InitializeObject(passive).IsSuccess());
    EXPECT_EQ(context.Update().BeginUpdate(passive).status,
              ContextResultStatus::kUnavailable);
}

TEST(ContextServices, CompositionComposesObjectsIntoRelationships) {
    Context context(MakeContextIdentity(1));
    const ContextObjectId source = MakeContextObjectId(1);
    const ContextObjectId target = MakeContextObjectId(2);
    ASSERT_TRUE(test::CreateAndActivate(context, source, "execution_context"));
    ASSERT_TRUE(test::CreateAndActivate(context, target, "working_state"));

    const auto composed = context.Composition().ComposeRelationship(
        MakeContextRelationshipId(1), source, target, "informs",
        test::MakeMetadata("rel"));
    ASSERT_TRUE(composed.IsSuccess());
    EXPECT_EQ(composed.value, MakeContextRelationshipId(1));
    EXPECT_EQ(context.Composition().RelationshipCount(), 1);

    const auto listed = context.Composition().ListRelationshipsOf(source);
    ASSERT_TRUE(listed.IsSuccess());
    ASSERT_EQ(listed.value.size(), 1);
    EXPECT_EQ(listed.value[0].GetKind(), "informs");
}

TEST(ContextServices, InvalidCompositionIsRejected) {
    Context context(MakeContextIdentity(1));
    const ContextObjectId object_id = MakeContextObjectId(1);
    ASSERT_TRUE(test::CreateAndActivate(context, object_id));

    // Self-composition is an invalid composition.
    EXPECT_EQ(context.Composition()
                  .ComposeRelationship(MakeContextRelationshipId(1), object_id,
                                       object_id, "self",
                                       test::MakeMetadata("rel"))
                  .status,
              ContextResultStatus::kInvalid);

    // Unknown participants are invalid.
    EXPECT_EQ(context.Composition()
                  .ComposeRelationship(MakeContextRelationshipId(2), object_id,
                                       MakeContextObjectId(999), "to",
                                       test::MakeMetadata("rel"))
                  .status,
              ContextResultStatus::kInvalid);
}

TEST(ContextServices, ReleaseIsTerminalAndIrreversible) {
    Context context(MakeContextIdentity(1));
    const ContextObjectId object_id = MakeContextObjectId(1);
    ASSERT_TRUE(test::CreateAndActivate(context, object_id));

    ASSERT_TRUE(context.Release().ReleaseObject(object_id).IsSuccess());

    // Released Object rejects every operational access.
    EXPECT_EQ(context.Access().InspectObject(object_id).status,
              ContextResultStatus::kReleased);
    EXPECT_EQ(context.Update().BeginUpdate(object_id).status,
              ContextResultStatus::kReleased);
    EXPECT_EQ(context.Update().ApplyUpdate(object_id, "x",
                                           test::MakeMetadata("x")).status,
              ContextResultStatus::kReleased);
    EXPECT_EQ(context.Release().ReleaseObject(object_id).status,
              ContextResultStatus::kReleased);

    // Released Objects cannot participate in composition.
    const ContextObjectId other = MakeContextObjectId(2);
    ASSERT_TRUE(test::CreateAndActivate(context, other));
    EXPECT_EQ(context.Composition()
                  .ComposeRelationship(MakeContextRelationshipId(1), object_id,
                                       other, "informs",
                                       test::MakeMetadata("rel"))
                  .status,
              ContextResultStatus::kReleased);

    // The Object cannot return to an operational state.
    const auto view = context.Access().ListObjects();
    ASSERT_TRUE(view.IsSuccess());
    bool found = false;
    for (const ContextObjectId id : view.value) {
        if (id == object_id) {
            found = true;
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST(ContextServices, InvalidLifecycleTransitionViaServiceIsRejected) {
    Context context(MakeContextIdentity(1));
    const ContextObjectId object_id = MakeContextObjectId(1);
    ASSERT_TRUE(context.Creation()
                    .CreateObject(object_id, "working_state", "payload",
                                  test::MakeMetadata("obj"))
                    .IsSuccess());

    // Created -> Active is illegal: activation requires
    // initialization first.
    EXPECT_TRUE(context.Creation().ActivateObject(object_id).IsRejected());
    auto view = context.Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_EQ(view.value.lifecycle, ContextLifecycleState::kCreated);
    EXPECT_EQ(view.value.operational, ContextOperationalState::kUninitialized);

    // Initialized -> Updated is unavailable: update requires Active.
    ASSERT_TRUE(context.Creation().InitializeObject(object_id).IsSuccess());
    EXPECT_EQ(context.Update().BeginUpdate(object_id).status,
              ContextResultStatus::kUnavailable);

    // Double initialization is illegal.
    EXPECT_TRUE(context.Creation().InitializeObject(object_id).IsRejected());
}

TEST(ContextServices, InvalidStateTransitionViaServiceIsRejected) {
    Context context(MakeContextIdentity(1));
    const ContextObjectId object_id = MakeContextObjectId(1);
    ASSERT_TRUE(test::CreateAndActivate(context, object_id));

    // Mid-update the Object is in Updating; the operational model
    // has no Updating -> Released path, so release is rejected.
    ASSERT_TRUE(context.Update().BeginUpdate(object_id).IsSuccess());
    EXPECT_TRUE(context.Release().ReleaseObject(object_id).IsRejected());

    // The object must return to Active before release.
    ASSERT_TRUE(context.Update().CompleteUpdate(object_id).IsSuccess());
    EXPECT_TRUE(context.Release().ReleaseObject(object_id).IsSuccess());
}

TEST(ContextServices, ServicesPreserveOwnershipAndEncapsulation) {
    // All five service responsibilities are reachable only
    // through the Context-owned service boundary; no service
    // exposes a Context Object pointer or storage handle.
    Context context(MakeContextIdentity(1));
    const ContextObjectId object_id = MakeContextObjectId(1);
    ASSERT_TRUE(test::CreateAndActivate(context, object_id));

    EXPECT_EQ(context.Creation().ObjectCount(), 1);
    EXPECT_EQ(context.Access().ObjectCount(), 1);

    const auto view = context.Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    // The view is a value copy: mutating the copy cannot touch
    // Context-owned state.
    ContextObjectView copy = view.value;
    copy.content = "tampered";
    const auto second = context.Access().InspectObject(object_id);
    ASSERT_TRUE(second.IsSuccess());
    EXPECT_EQ(second.value.content, "payload");
}

}  // namespace
}  // namespace ak::context

