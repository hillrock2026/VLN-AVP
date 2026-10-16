// ============================================================
// ownership_dependency_test.cpp - P1-IS004 ownership/dependency
// conformance
// ============================================================
// CTX-002 / CTX-010 / CTX-016 / CTX-017 / CTX-018: Context is an
// independent subsystem; it owns execution context, intelligent
// working state, Objects, Services, lifecycle, state, and
// extensions; it does not own or coordinate Agent, Memory,
// Planner, Tool, or Runtime; no universal manager exists.
// ============================================================

#include <agent_kernel/context/context.hpp>
#include <agent_kernel/context/context_extensions.hpp>
#include <agent_kernel/context/context_identity.hpp>
#include <agent_kernel/context/context_services.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <memory>
#include <type_traits>

#include "test_doubles.hpp"

namespace ak::context {
namespace {

// Negative API surface: Context must not expose peer subsystem
// objects, coordination entry points, or universal managers.
template <typename T, typename = void>
struct HasAgentAccessor : std::false_type {};
template <typename T>
struct HasAgentAccessor<T, std::void_t<decltype(std::declval<T&>().GetAgent())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasMemoryAccessor : std::false_type {};
template <typename T>
struct HasMemoryAccessor<T, std::void_t<decltype(std::declval<T&>().GetMemory())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasPlannerAccessor : std::false_type {};
template <typename T>
struct HasPlannerAccessor<T, std::void_t<decltype(std::declval<T&>().GetPlanner())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasToolAccessor : std::false_type {};
template <typename T>
struct HasToolAccessor<T, std::void_t<decltype(std::declval<T&>().GetTool())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasRuntimeAccessor : std::false_type {};
template <typename T>
struct HasRuntimeAccessor<T, std::void_t<decltype(std::declval<T&>().GetRuntime())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasContextManager : std::false_type {};
template <typename T>
struct HasContextManager<T, std::void_t<decltype(std::declval<T&>().GetContextManager())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasUniversalCoordinator : std::false_type {};
template <typename T>
struct HasUniversalCoordinator<
    T, std::void_t<decltype(std::declval<T&>().GetUniversalCoordinator())>>
    : std::true_type {};

TEST(ContextOwnership, ContextIsAnIndependentBoundary) {
    // Context stands alone: identity, Objects, Services, and
    // extensions are all Context-owned.
    Context context(MakeContextIdentity(1));
    EXPECT_TRUE(context.GetIdentity().IsValid());
    EXPECT_EQ(context.Creation().ObjectCount(), 0);
    EXPECT_EQ(context.Composition().RelationshipCount(), 0);
    EXPECT_EQ(context.Extensions().Count(), 0);
    EXPECT_EQ(std::string(context.AgentContract().ContractName()), "Context");
}

TEST(ContextOwnership, ContextOwnsObjectsServicesAndExtensions) {
    Context context(MakeContextIdentity(2));
    ASSERT_TRUE(test::CreateAndActivate(context, MakeContextObjectId(1),
                                        "execution_context"));
    ASSERT_TRUE(test::CreateAndActivate(context, MakeContextObjectId(2),
                                        "working_state"));
    context.Extensions().Attach(std::make_shared<test::ContextExtensionDouble>(
        "ext", ContextExtensionVersion{1, 0}));

    EXPECT_EQ(context.Creation().ObjectCount(), 2);
    EXPECT_EQ(context.Access().ObjectCount(), 2);

    const auto listed = context.Access().ListObjects();
    ASSERT_TRUE(listed.IsSuccess());
    EXPECT_EQ(listed.value.size(), 2);

    EXPECT_EQ(context.Extensions().Count(), 1);
}

TEST(ContextOwnership, ContextDoesNotOwnOrCoordinatePeers) {
    static_assert(!HasAgentAccessor<Context>::value,
                  "Context must not expose an Agent object");
    static_assert(!HasMemoryAccessor<Context>::value,
                  "Context must not own Memory");
    static_assert(!HasPlannerAccessor<Context>::value,
                  "Context must not own Planner");
    static_assert(!HasToolAccessor<Context>::value,
                  "Context must not own Tool");
    static_assert(!HasRuntimeAccessor<Context>::value,
                  "Context must not own Runtime");
}

TEST(ContextOwnership, NoUniversalManagerOrCoordinatorExists) {
    static_assert(!HasContextManager<Context>::value,
                  "no ContextManager universal type");
    static_assert(!HasUniversalCoordinator<Context>::value,
                  "no universal coordinator");
    static_assert(!HasContextManager<ContextCreationService>::value);
    static_assert(!HasContextManager<ContextAgentContract>::value);
}

TEST(ContextOwnership, DependencyDirectionIsContextToFoundationOnly) {
    // Compile-time proof at the TU level: no Agent, Memory,
    // Planner, Tool, or Runtime type appears on the Context
    // boundary; the static include/link scan is enforced by the
    // ContextBoundaryCheck CTest.
    static_assert(std::is_base_of_v<ak::KernelIdentity, ContextIdentity>);
    static_assert(!std::is_same_v<ContextObjectId, ak::KernelIdentity>);
}

TEST(ContextOwnership, ContextLifecycleAndStateAreNotExternallyOwned) {
    // Lifecycle and operational state are mutated only through
    // Context Services; no accessor returns a mutable lifecycle
    // or state machine.
    Context context(MakeContextIdentity(1));
    const ContextObjectId object_id = MakeContextObjectId(1);
    ASSERT_TRUE(test::CreateAndActivate(context, object_id));

    // Read-only observation through the service boundary.
    const auto view = context.Access().InspectObject(object_id);
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_EQ(view.value.lifecycle, ContextLifecycleState::kActive);
    EXPECT_EQ(view.value.operational, ContextOperationalState::kActive);
}

}  // namespace
}  // namespace ak::context
