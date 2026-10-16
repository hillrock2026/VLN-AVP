// ============================================================
// context_boundary_validator_test.cpp - P1-IS004 representation
// validation
// ============================================================
// CTX-015 / CTX-020: the Context boundary validator confirms the
// Context representation is conforming (identity, Object
// invariants, extension isolation, lifecycle/state separation)
// and reports diagnostics for non-conforming representations.
// ============================================================

#include <agent_kernel/context/context.hpp>
#include <agent_kernel/context/context_boundary_validator.hpp>

#include <gtest/gtest.h>

#include <memory>
#include <type_traits>

#include "test_doubles.hpp"

namespace ak::context {
namespace {

TEST(ContextBoundaryValidator, ConformingContextProducesNoErrors) {
    Context context(MakeContextIdentity(1));
    ASSERT_TRUE(test::CreateAndActivate(context, MakeContextObjectId(1),
                                        "execution_context"));
    ASSERT_TRUE(test::CreateAndActivate(context, MakeContextObjectId(2),
                                        "working_state"));
    context.Extensions().Attach(std::make_shared<test::ContextExtensionDouble>(
        "ext", ContextExtensionVersion{1, 0}));

    ak::DiagnosticSink sink;
    ContextBoundaryValidator validator;
    validator.Validate(context, sink);

    EXPECT_FALSE(sink.HasErrors());
}

TEST(ContextBoundaryValidator, InvalidIdentityIsReported) {
    // A Context without a valid identity is non-conforming.
    Context context(MakeContextIdentity(0));

    ak::DiagnosticSink sink;
    ContextBoundaryValidator validator;
    validator.Validate(context, sink);

    EXPECT_TRUE(sink.HasErrors());
}

TEST(ContextBoundaryValidator, LifecycleAndStateRemainDistinct) {
    // Compile-time separation proof lives in the validator.
    static_assert(ContextBoundaryValidator::Phase2HasNoConcreteRuntimeDependency());
    static_assert(!std::is_same_v<ContextLifecycleState,
                                  ContextOperationalState>);
}

TEST(ContextBoundaryValidator, ServicesDriveConsistentLockstepState) {
    // After a full service-driven lifecycle, validation sees a
    // consistent representation (released in both dimensions).
    Context context(MakeContextIdentity(1));
    const ContextObjectId object_id = MakeContextObjectId(1);
    ASSERT_TRUE(test::CreateAndActivate(context, object_id));
    ASSERT_TRUE(context.Update().BeginUpdate(object_id).IsSuccess());
    ASSERT_TRUE(context.Update().CompleteUpdate(object_id).IsSuccess());
    ASSERT_TRUE(context.Release().ReleaseObject(object_id).IsSuccess());

    ak::DiagnosticSink sink;
    ContextBoundaryValidator validator;
    validator.Validate(context, sink);
    EXPECT_FALSE(sink.HasErrors());
}

}  // namespace
}  // namespace ak::context

