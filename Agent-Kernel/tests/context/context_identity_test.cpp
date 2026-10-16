// ============================================================
// context_identity_test.cpp - P1-IS004 identity conformance
// ============================================================
// CTX-001 / CTX-019: Context is an independent subsystem with a
// Context-owned identity domain; every Context Object carries a
// stable, Context-owned identity for its architectural lifetime;
// Object and Relationship identity domains cannot be mixed at
// compile time.
// ============================================================

#include <agent_kernel/context/context.hpp>
#include <agent_kernel/context/context_identity.hpp>

#include <gtest/gtest.h>

#include <type_traits>

#include "test_doubles.hpp"

namespace ak::context {
namespace {

TEST(ContextIdentity, ContextOwnsItsOwnIdentityDomain) {
    // Context identity is a distinct typed identity domain; it is
    // not a Memory, Agent, or Runtime identity.
    static_assert(std::is_base_of_v<ak::KernelIdentity, ContextIdentity>);
    static_assert(std::is_base_of_v<ak::KernelIdentity, ContextObjectId>);
    static_assert(std::is_base_of_v<ak::KernelIdentity, ContextRelationshipId>);

    const ContextIdentity identity = MakeContextIdentity(42);
    EXPECT_TRUE(identity.IsValid());
    EXPECT_EQ(identity.Value(), 42);
}

TEST(ContextIdentity, DefaultIdentityIsInvalid) {
    const ContextIdentity identity;
    const ContextObjectId object_id;
    const ContextRelationshipId relationship_id;
    EXPECT_FALSE(identity.IsValid());
    EXPECT_FALSE(object_id.IsValid());
    EXPECT_FALSE(relationship_id.IsValid());
}

TEST(ContextIdentity, ObjectAndRelationshipDomainsAreDistinct) {
    // Distinct tag types prevent accidental mixing at compile
    // time.
    static_assert(!std::is_same_v<ContextObjectId, ContextRelationshipId>);
    static_assert(!std::is_same_v<ContextObjectId, ContextIdentity>);

    const ContextObjectId object_id = MakeContextObjectId(7);
    const ContextRelationshipId relationship_id =
        MakeContextRelationshipId(7);
    EXPECT_EQ(object_id.Value(), relationship_id.Value());
}

TEST(ContextIdentity, ObjectIdentityIsStableAcrossLifetime) {
    Context context(MakeContextIdentity(1));
    const ContextObjectId object_id = MakeContextObjectId(101);

    ASSERT_TRUE(context.Creation()
                    .CreateObject(object_id, "execution_context", "payload",
                                  test::MakeMetadata("obj"))
                    .IsSuccess());
    ASSERT_TRUE(context.Creation().InitializeObject(object_id).IsSuccess());

    const auto view = context.Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    // Identity survives creation, initialization, and inspection.
    EXPECT_EQ(view.value.id, object_id);

    // Identity is Context-owned: the Context root carries its own
    // identity that is distinct from every Object identity.
    EXPECT_NE(context.GetIdentity(), ContextIdentity(object_id.Value()));
    EXPECT_TRUE(context.GetIdentity().IsValid());
}

}  // namespace
}  // namespace ak::context

