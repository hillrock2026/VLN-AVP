// ============================================================
// planner_foundation_reuse_test.cpp - P1-IS005 Foundation reuse
// ============================================================
// PLN-005: Planner reuses only P1-IS001 Foundation infrastructure
// (TypedKernelIdentity, LifecycleState/TransitionResult/
// LifecycleTransitionValidator, KernelMetadata); no duplicate
// infrastructure types are introduced.
// ============================================================

#include <agent_kernel/foundation/kernel_identity.hpp>
#include <agent_kernel/foundation/kernel_lifecycle.hpp>
#include <agent_kernel/foundation/kernel_metadata.hpp>
#include <agent_kernel/planner/planner_identity.hpp>
#include <agent_kernel/planner/planner_metadata.hpp>
#include <agent_kernel/planner/planner_state.hpp>

#include <gtest/gtest.h>

#include <type_traits>

namespace ak::planner {
namespace {

TEST(PlannerFoundationReuse, IdentityDerivesFromFoundationKernelIdentity) {
    static_assert(std::is_base_of_v<ak::KernelIdentity, PlannerIdentity>);
    static_assert(std::is_base_of_v<ak::KernelIdentity, PlannerSessionId>);
    static_assert(std::is_base_of_v<ak::KernelIdentity, PlanningRequestId>);
    static_assert(std::is_base_of_v<ak::KernelIdentity, PlanningResultId>);
    static_assert(std::is_base_of_v<ak::KernelIdentity, PlanningArtifactId>);
    static_assert(std::is_base_of_v<ak::KernelIdentity, ExecutionPlanId>);
}

TEST(PlannerFoundationReuse, LifecycleUsesFoundationLifecycleMechanics) {
    EXPECT_EQ(ToLifecycleState(PlannerLifecycleState::kReady).Value(), 2);
    const auto accepted = ValidatePlannerLifecycleTransition(
        PlannerLifecycleState::kCreated, PlannerLifecycleState::kInitializing);
    EXPECT_TRUE(accepted.Accepted());
    const auto rejected = ValidatePlannerLifecycleTransition(
        PlannerLifecycleState::kSuspended, PlannerLifecycleState::kTerminating);
    EXPECT_TRUE(rejected.Rejected());
}

TEST(PlannerFoundationReuse, MetadataComposesFoundationMetadata) {
    PlanningMetadata metadata;
    metadata.core.name = "planner-metadata";
    metadata.version = 3;
    EXPECT_EQ(metadata.core.name, "planner-metadata");
    EXPECT_EQ(metadata.version, 3);
    EXPECT_TRUE(metadata.annotations.empty());
}

}  // namespace
}  // namespace ak::planner
