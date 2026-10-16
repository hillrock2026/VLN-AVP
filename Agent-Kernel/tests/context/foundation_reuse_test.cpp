// ============================================================
// foundation_reuse_test.cpp - P1-IS004 Foundation conformance
// ============================================================
// CTX-014: Context reuses P1-IS001 Foundation mechanisms
// (identity, lifecycle validation, registries, metadata,
// diagnostics) while Foundation remains neutral; Foundation
// never owns Context lifecycle, state, Objects, Services, or
// extensions.
// ============================================================

#include <agent_kernel/foundation/kernel_diagnostics.hpp>
#include <agent_kernel/foundation/kernel_identity.hpp>
#include <agent_kernel/foundation/kernel_lifecycle.hpp>
#include <agent_kernel/foundation/kernel_metadata.hpp>
#include <agent_kernel/foundation/kernel_registry.hpp>
#include <agent_kernel/context/context.hpp>
#include <agent_kernel/context/context_identity.hpp>
#include <agent_kernel/context/context_state.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <memory>
#include <type_traits>
#include <utility>

#include "test_doubles.hpp"

namespace ak::context {
namespace {

TEST(ContextFoundationReuse, FoundationIdentityMechanicsAreReused) {
    // Context identity is a Foundation typed identity value; the
    // Foundation supplies mechanics only.
    static_assert(std::is_base_of_v<ak::KernelIdentity, ContextIdentity>);
    static_assert(std::is_base_of_v<ak::KernelIdentity, ContextObjectId>);

    const ContextIdentity identity = MakeContextIdentity(9);
    EXPECT_TRUE(identity.IsValid());
    EXPECT_EQ(identity.Value(), 9);
}

TEST(ContextFoundationReuse, FoundationLifecycleMechanicsAreReusedButNeutral) {
    // The Foundation validator is reused for validation; it is
    // not the lifecycle authority: it cannot change Context.
    ak::LifecycleTransitionValidator validator(&ContextLifecycleTransitionRule);
    EXPECT_TRUE(validator
                    .Validate(ToLifecycleState(ContextLifecycleState::kCreated),
                              ToLifecycleState(ContextLifecycleState::kInitialized))
                    .Accepted());
    EXPECT_TRUE(validator
                    .Validate(ToLifecycleState(ContextLifecycleState::kReleased),
                              ToLifecycleState(ContextLifecycleState::kActive))
                    .Rejected());

    Context context(MakeContextIdentity(1));
    const ContextObjectId object_id = MakeContextObjectId(1);
    ASSERT_TRUE(context.Creation()
                    .CreateObject(object_id, "working_state", "payload",
                                  test::MakeMetadata("obj"))
                    .IsSuccess());
    // Validation alone leaves Context state unchanged.
    (void)ValidateContextLifecycleTransition(ContextLifecycleState::kCreated,
                                             ContextLifecycleState::kInitialized);
    const auto view = context.Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_EQ(view.value.lifecycle, ContextLifecycleState::kCreated);
}

TEST(ContextFoundationReuse, FoundationMetadataAndDiagnosticsAreReused) {
    ak::KernelMetadata neutral;
    neutral.name = "context-config";
    Context context(MakeContextIdentity(2));
    context.SetConfiguration(neutral);
    EXPECT_EQ(context.GetConfiguration().name, "context-config");

    ak::DiagnosticSink sink;
    sink.Add(ak::DiagnosticSeverity::kInfo, 1, "info");
    EXPECT_EQ(sink.Count(), 1);
    EXPECT_FALSE(sink.HasErrors());
}

TEST(ContextFoundationReuse, RegistryMechanicsServeContextOwnership) {
    // Foundation registry mechanics are reused inside the Context
    // store; containment does not transfer ownership to the
    // Foundation, and Context semantics (duplicate rejection)
    // remain Context-owned.
    Context context(MakeContextIdentity(3));
    ASSERT_TRUE(context.Creation()
                    .CreateObject(MakeContextObjectId(1), "working_state",
                                  "a", test::MakeMetadata("a"))
                    .IsSuccess());
    // Context-owned duplicate semantics are enforced by Context
    // Services (Conflict), not by the registry overwriting.
    const auto duplicate = context.Creation().CreateObject(
        MakeContextObjectId(1), "working_state", "b",
        test::MakeMetadata("b"));
    EXPECT_EQ(duplicate.status, ContextResultStatus::kConflict);
    EXPECT_EQ(context.Creation().ObjectCount(), 1);
}

TEST(ContextFoundationReuse, FoundationDoesNotOwnContextSemantics) {
    // Foundation value types carry no Context semantics: the same
    // neutral metadata is Context-agnostic.
    ak::KernelMetadata neutral;
    neutral.name = "neutral";
    ContextMetadata context_metadata;
    context_metadata.core = neutral;
    context_metadata.version = 2;

    EXPECT_EQ(context_metadata.core.name, "neutral");
    EXPECT_EQ(context_metadata.version, 2);
}

}  // namespace
}  // namespace ak::context
