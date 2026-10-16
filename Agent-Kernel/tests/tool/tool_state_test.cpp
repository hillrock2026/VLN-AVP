// ============================================================
// tool_state_test.cpp - P1-IS006 Rev2 Chapter 33.3
// ============================================================
// State tests: lifecycle/state separation (TOL-029), state
// ownership (TOL-030, TOL-094), legal lifecycle/operational
// combinations (TOL-097), Restricted entry and exit
// (TOL-095/096), and constrained versus unconstrained
// capability behavior (TOL-098).
// ============================================================

#include <agent_kernel/tool/tool.hpp>

#include <gtest/gtest.h>

#include <string>

#include "test_doubles.hpp"

namespace ak::tool {
namespace {

TEST(ToolState, TOL_029_LifecycleAndOperationalStateAreSeparate) {
    Tool tool(ToolId("state-tool"),
              ToolConfiguration{"state", "1.0", "state test"});
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kInitializing);
    EXPECT_EQ(tool.OperationalState(), ToolOperationalState::kUninitialized);
    ASSERT_TRUE(tool.Register().Succeeded());
    // Both values are stored independently.
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kRegistered);
    EXPECT_EQ(tool.OperationalState(), ToolOperationalState::kRegistered);
    ASSERT_TRUE(tool.Activate().Succeeded());
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kAvailable);
    EXPECT_EQ(tool.OperationalState(), ToolOperationalState::kAvailable);
}

TEST(ToolState, TOL_097_LegalLifecycleOperationalCombinations) {
    Tool tool(ToolId("state-tool-2"),
              ToolConfiguration{"state", "1.0", "state test"});

    auto expect_legal = [&tool](ToolLifecycleState expected_lifecycle,
                                ToolOperationalState expected_operational) {
        EXPECT_EQ(tool.LifecycleState(), expected_lifecycle);
        EXPECT_EQ(tool.OperationalState(), expected_operational);
    };

    expect_legal(ToolLifecycleState::kInitializing,
                 ToolOperationalState::kUninitialized);
    ASSERT_TRUE(tool.Register().Succeeded());
    expect_legal(ToolLifecycleState::kRegistered,
                 ToolOperationalState::kRegistered);
    ASSERT_TRUE(tool.Activate().Succeeded());
    expect_legal(ToolLifecycleState::kAvailable,
                 ToolOperationalState::kAvailable);
    ASSERT_TRUE(tool.Suspend().Succeeded());
    expect_legal(ToolLifecycleState::kSuspended,
                 ToolOperationalState::kSuspended);
    ASSERT_TRUE(tool.Resume().Succeeded());
    expect_legal(ToolLifecycleState::kAvailable,
                 ToolOperationalState::kAvailable);
    ASSERT_TRUE(tool.Retire().Succeeded());
    expect_legal(ToolLifecycleState::kRetiring,
                 ToolOperationalState::kRetiring);
    ASSERT_TRUE(tool.FinalizeRetirement().Succeeded());
    expect_legal(ToolLifecycleState::kRetired,
                 ToolOperationalState::kRetired);
}

TEST(ToolState, TOL_095_RestrictedEntryFromConstrainedCapability) {
    Tool tool(ToolId("state-tool-3"),
              ToolConfiguration{"state", "1.0", "state test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    const auto result = tool.Capabilities().RegisterCapability(
        test::MakeCapability("constrained-cap", "provider-x",
                             CapabilityAvailability::kAvailable,
                             /*constrained=*/true));
    ASSERT_EQ(result.status, ToolResultStatus::kSuccess);
    // Activate re-evaluates the Restricted state (TOL-095).
    ASSERT_TRUE(tool.Activate().Succeeded());
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kAvailable);
    EXPECT_EQ(tool.OperationalState(), ToolOperationalState::kRestricted);
}

TEST(ToolState, TOL_096_RestrictedExitWhenNoCapabilityRemainsConstrained) {
    Tool tool(ToolId("state-tool-4"),
              ToolConfiguration{"state", "1.0", "state test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    ASSERT_EQ(tool.Capabilities().RegisterCapability(
                  test::MakeCapability("constrained-cap", "provider-x",
                                       CapabilityAvailability::kAvailable,
                                       /*constrained=*/true))
                  .status,
              ToolResultStatus::kSuccess);
    ASSERT_TRUE(tool.Activate().Succeeded());
    EXPECT_EQ(tool.OperationalState(), ToolOperationalState::kRestricted);

    // Replace the constrained capability with an unconstrained
    // one: re-evaluation exits kRestricted before returning.
    const auto replaced = tool.Capabilities().ReplaceCapability(
        test::MakeCapability("constrained-cap", "provider-x",
                             CapabilityAvailability::kAvailable,
                             /*constrained=*/false));
    ASSERT_EQ(replaced.status, ToolResultStatus::kSuccess);
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kAvailable);
    EXPECT_EQ(tool.OperationalState(), ToolOperationalState::kAvailable);
}

TEST(ToolState, TOL_095_RestrictedEntryFromUnavailableAvailability) {
    Tool tool(ToolId("state-tool-5"),
              ToolConfiguration{"state", "1.0", "state test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    ASSERT_EQ(tool.Capabilities().RegisterCapability(
                  test::MakeCapability("unavailable-cap", "provider-x",
                                       CapabilityAvailability::kUnavailable,
                                       /*constrained=*/false))
                  .status,
              ToolResultStatus::kSuccess);
    ASSERT_TRUE(tool.Activate().Succeeded());
    EXPECT_EQ(tool.OperationalState(), ToolOperationalState::kRestricted);
}

TEST(ToolState, TOL_098_ConstrainedCapabilityPreparationIsUnavailable) {
    Tool tool(ToolId("state-tool-6"),
              ToolConfiguration{"state", "1.0", "state test"});
    ASSERT_TRUE(tool.Register().Succeeded());

    auto provider = std::make_unique<test::TestToolProvider>("provider-a");
    provider->capabilities.push_back(
        test::MakeCapability("unconstrained-cap", "provider-a"));
    ASSERT_EQ(tool.Providers().Register(std::move(provider)).status,
              ToolResultStatus::kSuccess);

    ASSERT_EQ(tool.Capabilities().RegisterCapability(
                  test::MakeCapability("constrained-cap", "provider-a",
                                       CapabilityAvailability::kAvailable,
                                       /*constrained=*/true))
                  .status,
              ToolResultStatus::kSuccess);
    ASSERT_TRUE(tool.Activate().Succeeded());
    EXPECT_EQ(tool.OperationalState(), ToolOperationalState::kRestricted);

    // Constrained capability: preparation unavailable.
    const InvocationPreparationResult constrained = tool.InvocationPreparation()
        .PrepareInvocation(InvocationRequest{CapabilityId("constrained-cap"),
                                             "req-1", "payload"});
    EXPECT_EQ(constrained.status, InvocationPreparationStatus::kUnavailable);

    // Unconstrained capability follows the lifecycle matrix.
    const InvocationPreparationResult unconstrained =
        tool.InvocationPreparation().PrepareInvocation(
            InvocationRequest{CapabilityId("unconstrained-cap"),
                              "req-2", "payload"});
    EXPECT_EQ(unconstrained.status, InvocationPreparationStatus::kPrepared);
}

TEST(ToolState, TOL_094_RestrictedStateIsToolOwned) {
    // No public operation outside the Tool root mutates the
    // operational state directly. Observable behavior: the
    // state transitions only through Tool-root lifecycle and
    // mutation operations.
    Tool tool(ToolId("state-tool-7"),
              ToolConfiguration{"state", "1.0", "state test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    ASSERT_TRUE(tool.Activate().Succeeded());
    EXPECT_EQ(tool.OperationalState(), ToolOperationalState::kAvailable);

    // External reads cannot alter it.
    (void)tool.Discovery().ListCapabilities();
    EXPECT_EQ(tool.OperationalState(), ToolOperationalState::kAvailable);
    (void)tool.Availability().IsToolAvailable();
    EXPECT_EQ(tool.OperationalState(), ToolOperationalState::kAvailable);
}

}  // namespace
}  // namespace ak::tool