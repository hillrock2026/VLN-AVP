// ============================================================
// tool_lifecycle_test.cpp - P1-IS006 Rev2 Chapter 33.2
// ============================================================
// Lifecycle tests: the full transition chain (TOL-020 through
// TOL-026), invalid transition rejection with no mutation
// (TOL-019, TOL-065), terminal behavior (TOL-027), and
// deterministic lifecycle results carrying the state observed
// at the linearization point (TOL-028).
// ============================================================

#include <agent_kernel/tool/tool.hpp>

#include <gtest/gtest.h>

#include <string>

namespace ak::tool {
namespace {

Tool MakeTool(const char* id = "lifecycle-tool") {
    return Tool(ToolId(id),
                ToolConfiguration{"lifecycle", "1.0", "lifecycle test"});
}

TEST(ToolLifecycle, TOL_020_ConstructionStartsInitializing) {
    Tool tool = MakeTool();
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kInitializing);
    EXPECT_EQ(tool.OperationalState(), ToolOperationalState::kUninitialized);
}

TEST(ToolLifecycle, TOL_021_RegistrationTransition) {
    Tool tool = MakeTool();
    const ToolLifecycleResult result = tool.Register();
    EXPECT_TRUE(result.Succeeded());
    EXPECT_EQ(result.status, ToolLifecycleResultStatus::kSuccess);
    EXPECT_EQ(result.state, ToolLifecycleState::kRegistered);
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kRegistered);
    EXPECT_TRUE(tool.Registration().IsRegistered());
}

TEST(ToolLifecycle, TOL_022_ActivationTransition) {
    Tool tool = MakeTool();
    ASSERT_TRUE(tool.Register().Succeeded());
    const ToolLifecycleResult result = tool.Activate();
    EXPECT_TRUE(result.Succeeded());
    EXPECT_EQ(result.state, ToolLifecycleState::kAvailable);
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kAvailable);
}

TEST(ToolLifecycle, TOL_023_SuspensionTransition) {
    Tool tool = MakeTool();
    ASSERT_TRUE(tool.Register().Succeeded());
    ASSERT_TRUE(tool.Activate().Succeeded());
    const ToolLifecycleResult result = tool.Suspend();
    EXPECT_TRUE(result.Succeeded());
    EXPECT_EQ(result.state, ToolLifecycleState::kSuspended);
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kSuspended);
}

TEST(ToolLifecycle, TOL_024_ResumeTransition) {
    Tool tool = MakeTool();
    ASSERT_TRUE(tool.Register().Succeeded());
    ASSERT_TRUE(tool.Activate().Succeeded());
    ASSERT_TRUE(tool.Suspend().Succeeded());
    const ToolLifecycleResult result = tool.Resume();
    EXPECT_TRUE(result.Succeeded());
    EXPECT_EQ(result.state, ToolLifecycleState::kAvailable);
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kAvailable);
}

TEST(ToolLifecycle, TOL_025_RetirementAdmission) {
    Tool tool = MakeTool();
    ASSERT_TRUE(tool.Register().Succeeded());
    ASSERT_TRUE(tool.Activate().Succeeded());
    const ToolLifecycleResult result = tool.Retire();
    EXPECT_TRUE(result.Succeeded());
    EXPECT_EQ(result.state, ToolLifecycleState::kRetiring);
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kRetiring);
    EXPECT_EQ(tool.OperationalState(), ToolOperationalState::kRetiring);
}

TEST(ToolLifecycle, TOL_026_FinalRetirement) {
    Tool tool = MakeTool();
    ASSERT_TRUE(tool.Register().Succeeded());
    ASSERT_TRUE(tool.Activate().Succeeded());
    ASSERT_TRUE(tool.Retire().Succeeded());
    const ToolLifecycleResult result = tool.FinalizeRetirement();
    EXPECT_TRUE(result.Succeeded());
    EXPECT_EQ(result.state, ToolLifecycleState::kRetired);
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kRetired);
    EXPECT_EQ(tool.OperationalState(), ToolOperationalState::kRetired);
}

TEST(ToolLifecycle, TOL_019_OnlyArchitecturalTransitionsAreAccepted) {
    // From kInitializing only Register() is legal.
    Tool tool = MakeTool();
    EXPECT_EQ(tool.Activate().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.Suspend().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.Resume().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.Retire().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.FinalizeRetirement().status,
              ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kInitializing);

    // From kRegistered only Activate() is legal.
    ASSERT_TRUE(tool.Register().Succeeded());
    EXPECT_EQ(tool.Register().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.Suspend().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.Resume().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.Retire().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.FinalizeRetirement().status,
              ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kRegistered);

    // From kAvailable only Suspend()/Retire() are legal.
    ASSERT_TRUE(tool.Activate().Succeeded());
    EXPECT_EQ(tool.Activate().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.Resume().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kAvailable);

    // From kSuspended only Resume() is legal.
    ASSERT_TRUE(tool.Suspend().Succeeded());
    EXPECT_EQ(tool.Suspend().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.Activate().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kSuspended);

    // From kRetiring only FinalizeRetirement() is legal.
    ASSERT_TRUE(tool.Resume().Succeeded());
    ASSERT_TRUE(tool.Retire().Succeeded());
    EXPECT_EQ(tool.Register().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.Activate().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.Suspend().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.Resume().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.Retire().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kRetiring);

    // From kRetired nothing is legal.
    ASSERT_TRUE(tool.FinalizeRetirement().Succeeded());
    EXPECT_EQ(tool.Register().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.Activate().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.Suspend().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.Resume().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.Retire().status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.FinalizeRetirement().status,
              ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kRetired);
}

TEST(ToolLifecycle, TOL_065_RejectedLifecycleDoesNotMutateState) {
    Tool tool = MakeTool();
    ASSERT_TRUE(tool.Register().Succeeded());
    ASSERT_TRUE(tool.Activate().Succeeded());
    ASSERT_TRUE(tool.Suspend().Succeeded());
    // From kSuspended only Resume() is legal; Activate() is rejected
    // and SHALL NOT mutate the lifecycle state (TOL-065).
    const ToolLifecycleResult rejected = tool.Activate();
    EXPECT_EQ(rejected.status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(rejected.state, ToolLifecycleState::kSuspended);
    // Rejected transitions leave the lifecycle state unchanged.
    const ToolLifecycleResult bad = tool.Suspend();
    EXPECT_EQ(bad.status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(bad.state, ToolLifecycleState::kSuspended);
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kSuspended);
    EXPECT_EQ(tool.OperationalState(), ToolOperationalState::kSuspended);
}

TEST(ToolLifecycle, TOL_027_RetiredToolCannotBeResurrected) {
    Tool tool = MakeTool();
    ASSERT_TRUE(tool.Register().Succeeded());
    ASSERT_TRUE(tool.Activate().Succeeded());
    ASSERT_TRUE(tool.Retire().Succeeded());
    ASSERT_TRUE(tool.FinalizeRetirement().Succeeded());
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kRetired);
    EXPECT_EQ(tool.OperationalState(), ToolOperationalState::kRetired);
}

TEST(ToolLifecycle, TOL_028_ResultCarriesStateAtLinearizationPoint) {
    Tool tool = MakeTool();
    const ToolLifecycleResult result = tool.Register();
    EXPECT_EQ(result.state, ToolLifecycleState::kRegistered);
    EXPECT_EQ(result.state, tool.LifecycleState());
}

TEST(ToolLifecycle, TOL_082_RegisteredIdentityPersistsThroughRetirement) {
    Tool tool = MakeTool("identity-persists");
    ASSERT_TRUE(tool.Register().Succeeded());
    ASSERT_TRUE(tool.Activate().Succeeded());
    ASSERT_TRUE(tool.Retire().Succeeded());
    ASSERT_TRUE(tool.FinalizeRetirement().Succeeded());
    // The registered Tool identity remains unchanged (AK0045
    // 5.3); retirement does not delete or mutate it.
    EXPECT_EQ(tool.Id(), ToolId("identity-persists"));
}

}  // namespace
}  // namespace ak::tool