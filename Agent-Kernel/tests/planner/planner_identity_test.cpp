// ============================================================
// planner_identity_test.cpp - P1-IS005 identity model
// ============================================================
// PLN-010/011/012/022: six typed identity domains are distinct
// TypedKernelIdentity values; default construction is invalid;
// cross-domain assignment is a compile-time error; session
// identity is distinct from every other domain.
// ============================================================

#include <agent_kernel/planner/planner_identity.hpp>

#include <gtest/gtest.h>

#include <functional>
#include <type_traits>

namespace ak::planner {
namespace {

TEST(PlannerIdentity, DefaultConstructionIsInvalid) {
    EXPECT_FALSE(PlannerIdentity().IsValid());
    EXPECT_FALSE(PlannerSessionId().IsValid());
    EXPECT_FALSE(PlanningRequestId().IsValid());
    EXPECT_FALSE(PlanningResultId().IsValid());
    EXPECT_FALSE(PlanningArtifactId().IsValid());
    EXPECT_FALSE(ExecutionPlanId().IsValid());
}

TEST(PlannerIdentity, FactoriesProduceValidValues) {
    EXPECT_TRUE(MakePlannerIdentity(1).IsValid());
    EXPECT_TRUE(MakePlannerSessionId(1).IsValid());
    EXPECT_TRUE(MakePlanningRequestId(1).IsValid());
    EXPECT_TRUE(MakePlanningResultId(1).IsValid());
    EXPECT_TRUE(MakePlanningArtifactId(1).IsValid());
    EXPECT_TRUE(MakeExecutionPlanId(1).IsValid());
    EXPECT_EQ(MakePlannerIdentity(7).Value(), 7);
    EXPECT_EQ(MakeExecutionPlanId(9).Value(), 9);
}

TEST(PlannerIdentity, SixDomainsAreDistinctTypes) {
    static_assert(!std::is_same_v<PlannerIdentity, PlannerSessionId>);
    static_assert(!std::is_same_v<PlannerSessionId, PlanningRequestId>);
    static_assert(!std::is_same_v<PlanningRequestId, PlanningResultId>);
    static_assert(!std::is_same_v<PlanningResultId, PlanningArtifactId>);
    static_assert(!std::is_same_v<PlanningArtifactId, ExecutionPlanId>);
    static_assert(!std::is_same_v<PlannerIdentity, ExecutionPlanId>);
}

TEST(PlannerIdentity, CrossDomainAssignmentIsRejectedAtCompileTime) {
    static_assert(!std::is_convertible_v<PlannerIdentity, PlannerSessionId>);
    static_assert(!std::is_convertible_v<PlannerSessionId, PlanningRequestId>);
    static_assert(!std::is_convertible_v<PlanningRequestId, PlanningResultId>);
    static_assert(!std::is_convertible_v<PlanningResultId, PlanningArtifactId>);
    static_assert(!std::is_convertible_v<ExecutionPlanId, PlanningRequestId>);
    static_assert(!std::is_convertible_v<PlannerSessionId, PlannerIdentity>);
}

TEST(PlannerIdentity, PrimarySessionIdConstantIsValid) {
    EXPECT_NE(kPrimaryPlannerSessionIdValue, 0);
    EXPECT_TRUE(MakePlannerSessionId(kPrimaryPlannerSessionIdValue).IsValid());
}

TEST(PlannerIdentity, HashIsSupportedForRegistryKeys) {
    const std::hash<PlanningRequestId> request_hasher;
    const PlanningRequestId request = MakePlanningRequestId(5);
    EXPECT_EQ(request_hasher(request), request_hasher(MakePlanningRequestId(5)));

    const std::hash<PlanningArtifactId> artifact_hasher;
    const PlanningArtifactId artifact = MakePlanningArtifactId(5);
    EXPECT_EQ(artifact_hasher(artifact), artifact_hasher(MakePlanningArtifactId(5)));

    const std::hash<ExecutionPlanId> plan_hasher;
    const ExecutionPlanId plan = MakeExecutionPlanId(5);
    EXPECT_EQ(plan_hasher(plan), plan_hasher(MakeExecutionPlanId(5)));

    const std::hash<PlannerSessionId> session_hasher;
    const PlannerSessionId session = MakePlannerSessionId(5);
    EXPECT_EQ(session_hasher(session), session_hasher(MakePlannerSessionId(5)));
}

}  // namespace
}  // namespace ak::planner
