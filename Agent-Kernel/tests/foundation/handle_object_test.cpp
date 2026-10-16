// ============================================================
// handle_object_test.cpp - P1-IS001 handle/object boundary
// ============================================================
// Verifies:
// - KernelHandle is a non-owning, ownership-neutral reference.
// - Handles, containment, and object mechanics do not transfer
//   architectural ownership.
// - KernelObject provides only neutral mechanics (identity,
//   metadata) and no lifecycle/state authority.
// ============================================================

#include <agent_kernel/foundation/kernel_handle.hpp>
#include <agent_kernel/foundation/kernel_identity.hpp>
#include <agent_kernel/foundation/kernel_metadata.hpp>
#include <agent_kernel/foundation/kernel_object.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <type_traits>
#include <unordered_set>
#include <utility>

namespace ak {
namespace {

// ------------------------------------------------------------
// SFINAE member detectors (structural conformance checks)
// ------------------------------------------------------------
template <typename T, typename = void>
struct HasResolve : std::false_type {};
template <typename T>
struct HasResolve<T, std::void_t<decltype(std::declval<T&>().Resolve())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasInitialize : std::false_type {};
template <typename T>
struct HasInitialize<T, std::void_t<decltype(std::declval<T&>().Initialize())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasDestroy : std::false_type {};
template <typename T>
struct HasDestroy<T, std::void_t<decltype(std::declval<T&>().Destroy())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasGetState : std::false_type {};
template <typename T>
struct HasGetState<T, std::void_t<decltype(std::declval<T&>().GetState())>>
    : std::true_type {};

// ------------------------------------------------------------
// KernelHandle
// ------------------------------------------------------------
TEST(KernelHandle, DefaultIsInvalid) {
    KernelHandle<int, KernelIdentity> handle;
    EXPECT_FALSE(handle.IsValid());
}

TEST(KernelHandle, CarriesIdentityAndGeneration) {
    KernelHandle<int, KernelIdentity> handle(KernelIdentity(11), 3);
    EXPECT_TRUE(handle.IsValid());
    EXPECT_EQ(handle.GetID(), KernelIdentity(11));
    EXPECT_EQ(handle.GetGeneration(), 3);
}

TEST(KernelHandle, IsCopyableValueWithoutOwning) {
    // The handle holds only identity + generation. Copying it
    // does not duplicate or extend the lifetime of any object.
    using TestHandle = KernelHandle<int, KernelIdentity>;
    TestHandle first(KernelIdentity(1), 1);
    TestHandle second = first;
    EXPECT_EQ(second, first);
    EXPECT_EQ(std::hash<TestHandle>()(second), std::hash<TestHandle>()(first));
}

TEST(KernelHandle, DoesNotOwnAndCannotResolve) {
    // A handle is ownership-neutral: it has no pointer storage
    // and no resolution/lifetime API on the Foundation surface.
    static_assert(!HasResolve<KernelHandle<int, KernelIdentity>>::value,
                  "Foundation handle must not resolve to concrete objects");
}

TEST(KernelHandle, IsUsableInContainers) {
    std::unordered_set<KernelHandle<int, KernelIdentity>> handles;
    handles.insert(KernelHandle<int, KernelIdentity>(KernelIdentity(1), 1));
    handles.insert(KernelHandle<int, KernelIdentity>(KernelIdentity(1), 1));
    handles.insert(KernelHandle<int, KernelIdentity>(KernelIdentity(2), 1));
    EXPECT_EQ(handles.size(), 2);
}

// ------------------------------------------------------------
// Test-local owner object (no subsystem dependency)
// ------------------------------------------------------------
class TestObjectID {
public:
    explicit TestObjectID(std::uint64_t value) noexcept : value_(value) {}
    [[nodiscard]] std::uint64_t Value() const noexcept { return value_; }
    auto operator<=>(const TestObjectID&) const = default;

private:
    std::uint64_t value_ = 0;
};

class TestObject : public TypedKernelObject<TestObject, TestObjectID> {
public:
    explicit TestObject(TestObjectID id)
        : TypedKernelObject<TestObject, TestObjectID>(id) {}

    [[nodiscard]] const KernelMetadata& GetMetadata() const noexcept override {
        return metadata_;
    }

    void SetMetadata(const KernelMetadata& metadata) override {
        metadata_ = metadata;
    }

private:
    KernelMetadata metadata_;
};

// ------------------------------------------------------------
// KernelObject / TypedKernelObject
// ------------------------------------------------------------
TEST(KernelObject, BaseExposesOnlyNeutralMechanics) {
    // Identity + metadata access are neutral mechanics.
    static_assert(std::is_abstract_v<KernelObject>);
    // Lifecycle authority and subsystem state semantics are
    // deliberately absent from the Foundation base.
    static_assert(!HasInitialize<KernelObject>::value,
                  "KernelObject must not declare Initialize()");
    static_assert(!HasDestroy<KernelObject>::value,
                  "KernelObject must not declare Destroy()");
    static_assert(!HasGetState<KernelObject>::value,
                  "KernelObject must not declare GetState()");
}

TEST(TypedKernelObject, ProvidesTypedAndNeutralIdentity) {
    TestObject object(TestObjectID(5));
    EXPECT_EQ(object.GetIDValue(), 5);
    EXPECT_EQ(object.GetID(), TestObjectID(5));
    EXPECT_EQ(object.GetIdentity(), KernelIdentity(5));
    EXPECT_TRUE(object.GetIdentity().IsValid());
}

TEST(KernelMetadata, IsNeutralContainmentNotOwnership) {
    TestObject object(TestObjectID(9));

    KernelMetadata metadata;
    metadata.name = "test-object";
    metadata.label = "TO";
    metadata.description = "neutral metadata";
    metadata.tags = {"a", "b"};

    // The object composes metadata mechanically; the object
    // controls its own metadata (containment is not ownership
    // transfer, and metadata itself owns no architecture).
    object.SetMetadata(metadata);
    EXPECT_EQ(object.GetMetadata().name, "test-object");
    EXPECT_EQ(object.GetMetadata().tags.size(), 2);

    KernelMetadata copy = object.GetMetadata();
    copy.name = "changed";
    EXPECT_EQ(object.GetMetadata().name, "test-object");
}

}  // namespace
}  // namespace ak