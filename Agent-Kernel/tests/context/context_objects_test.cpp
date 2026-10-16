// ============================================================
// context_objects_test.cpp - P1-IS004 object-boundary conformance
// ============================================================
// CTX-007 / CTX-019: Context Objects remain Context-owned value
// representations; they are distinct from Memory Objects and
// Runtime Objects; their internals (lifecycle, state, working
// state) are not directly mutable; access is encapsulated behind
// Context Services.
// ============================================================

#include <agent_kernel/context/context.hpp>
#include <agent_kernel/context/context_objects.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <type_traits>

#include "test_doubles.hpp"

namespace ak::context {
namespace {

// Negative API surface: no public mutator may exist on the
// Context Object representation.
template <typename T, typename = void>
struct HasSetContent : std::false_type {};
template <typename T>
struct HasSetContent<T, std::void_t<decltype(std::declval<T&>().SetContent(
                            std::declval<const std::string&>()))>>
    : std::true_type {};

template <typename T, typename = void>
struct HasSetLifecycleState : std::false_type {};
template <typename T>
struct HasSetLifecycleState<
    T, std::void_t<decltype(std::declval<T&>().SetLifecycleState(
           std::declval<ContextLifecycleState>()))>> : std::true_type {};

template <typename T, typename = void>
struct HasSetOperationalState : std::false_type {};
template <typename T>
struct HasSetOperationalState<
    T, std::void_t<decltype(std::declval<T&>().SetOperationalState(
           std::declval<ContextOperationalState>()))>> : std::true_type {};

TEST(ContextObjects, ContextMetadataSupportsStructuralEquality) {
    const ContextMetadata a = test::MakeMetadata("a", 1);
    ContextMetadata b = test::MakeMetadata("a", 1);
    EXPECT_TRUE(a == b);
    b.annotations.push_back("extra");
    EXPECT_TRUE(a != b);
}

TEST(ContextObjects, ContextObjectIsAReadOnlyBoundaryValue) {
    Context context(MakeContextIdentity(1));
    const ContextObjectId object_id = MakeContextObjectId(1);
    const ContextMetadata metadata = test::MakeMetadata("obj", 2);
    ASSERT_TRUE(context.Creation()
                    .CreateObject(object_id, "execution_context", "payload",
                                  metadata)
                    .IsSuccess());

    const auto view = context.Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_EQ(view.value.id, object_id);
    EXPECT_EQ(view.value.category, "execution_context");
    EXPECT_EQ(view.value.content, "payload");
    EXPECT_EQ(view.value.metadata, metadata);
    EXPECT_EQ(view.value.lifecycle, ContextLifecycleState::kCreated);
    EXPECT_EQ(view.value.operational, ContextOperationalState::kUninitialized);
}

TEST(ContextObjects, ObjectInternalsAreNotDirectlyMutable) {
    // No direct mutation surface exists on Context Objects:
    // working state and lifecycle/state change only through
    // Context Services.
    static_assert(!HasSetContent<ContextObject>::value,
                  "Context Object working state must not be directly mutable");
    static_assert(!HasSetLifecycleState<ContextObject>::value,
                  "Context Object lifecycle must not be directly mutable");
    static_assert(!HasSetOperationalState<ContextObject>::value,
                  "Context Object state must not be directly mutable");
}

TEST(ContextObjects, ContextObjectsRemainContextOwnedValues) {
    // Context Objects are value representations owned by Context;
    // they are not Memory Objects, Runtime Objects, or Agent
    // lifecycle objects (no such type is referenced anywhere in
    // the Context boundary).
    static_assert(!std::is_same_v<ContextObjectId, ak::KernelIdentity>);
    EXPECT_TRUE(std::is_copy_constructible_v<ContextObjectView>);
    EXPECT_TRUE(std::is_copy_constructible_v<ContextRelationship>);
}

TEST(ContextObjects, RelationshipCarriesOnlyContextIdentity) {
    const ContextRelationship relationship(
        MakeContextRelationshipId(9), MakeContextObjectId(1),
        MakeContextObjectId(2), "depends_on", test::MakeMetadata("rel"));
    EXPECT_EQ(relationship.GetId(), MakeContextRelationshipId(9));
    EXPECT_EQ(relationship.GetSourceId(), MakeContextObjectId(1));
    EXPECT_EQ(relationship.GetTargetId(), MakeContextObjectId(2));
    EXPECT_EQ(relationship.GetKind(), "depends_on");
    // No storage id, address, index, or provider handle exists.
    EXPECT_EQ(relationship.GetMetadata().classification, "test");
}

}  // namespace
}  // namespace ak::context
