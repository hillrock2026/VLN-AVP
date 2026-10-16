// ============================================================
// tool_failure_test.cpp - P1-IS006 Rev2 Chapter 33.13
// ============================================================
// Failure tests: construction failure semantics (TOL-111,
// TOL-112), operation/state/result mapping (TOL-092),
// Provider callback failure normalization (TOL-093),
// deterministic failure (TOL-069), and no hidden recovery
// (TOL-070).
// ============================================================

#include <agent_kernel/tool/tool.hpp>

#include <gtest/gtest.h>

#include <memory>
#include <stdexcept>
#include <string>

#include "test_doubles.hpp"

namespace ak::tool {
namespace {

TEST(ToolFailure, TOL_111_IdentityConstructionFailure) {
    EXPECT_THROW(ToolId(""), std::invalid_argument);
    EXPECT_THROW(ToolId("   "), std::invalid_argument);
    EXPECT_THROW(CapabilityId(""), std::invalid_argument);
    EXPECT_THROW(ProviderId(""), std::invalid_argument);
}

TEST(ToolFailure, TOL_112_ConfigurationValidationFailure) {
    EXPECT_THROW(Tool(ToolId("tool-x"), ToolConfiguration{"", "1.0", ""}),
                 std::invalid_argument);
    EXPECT_THROW(Tool(ToolId("tool-x"), ToolConfiguration{"  ", "1.0", ""}),
                 std::invalid_argument);
    // Valid configuration constructs normally.
    Tool tool(ToolId("tool-x"), ToolConfiguration{"valid", "1.0", ""});
    EXPECT_EQ(tool.Id(), ToolId("tool-x"));
}

TEST(ToolFailure, TOL_092_MalformedInvocationRequestRejected) {
    Tool tool(ToolId("fail-tool"),
              ToolConfiguration{"failure", "1.0", "failure test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    auto provider = std::make_unique<test::TestToolProvider>("provider-a");
    provider->capabilities.push_back(
        test::MakeCapability("cap-a", "provider-a"));
    ASSERT_EQ(tool.Providers().Register(std::move(provider)).status,
              ToolResultStatus::kSuccess);
    ASSERT_TRUE(tool.Activate().Succeeded());
    // Empty request_id.
    EXPECT_EQ(tool.InvocationPreparation()
                  .PrepareInvocation(
                      InvocationRequest{CapabilityId("cap-a"), "", "payload"})
                  .status,
              InvocationPreparationStatus::kRejected);
    // Empty payload.
    EXPECT_EQ(tool.InvocationPreparation()
                  .PrepareInvocation(
                      InvocationRequest{CapabilityId("cap-a"), "req", ""})
                  .status,
              InvocationPreparationStatus::kRejected);
}

TEST(ToolFailure, TOL_092_UnknownCapabilityNotFoundEverywhere) {
    Tool tool(ToolId("fail-tool-2"),
              ToolConfiguration{"failure", "1.0", "failure test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    EXPECT_EQ(tool.Discovery().FindCapability(CapabilityId("unknown")).status,
              ToolResultStatus::kNotFound);
    EXPECT_EQ(tool.Capabilities().Get(CapabilityId("unknown")).status,
              ToolResultStatus::kNotFound);
    EXPECT_EQ(tool.Capabilities().GetContract(CapabilityId("unknown")).status,
              ToolResultStatus::kNotFound);
    EXPECT_EQ(tool.Capabilities().ReplaceCapability(
                  test::MakeCapability("unknown", "provider-a"))
                  .status,
              ToolResultStatus::kNotFound);
    EXPECT_EQ(tool.Availability().GetAvailability(CapabilityId("unknown")).status,
              ToolResultStatus::kNotFound);
    EXPECT_EQ(tool.Permissions().Check(CapabilityId("unknown"), {}).status,
              ToolResultStatus::kNotFound);
    EXPECT_EQ(tool.Providers().ProviderFor(CapabilityId("unknown")).status,
              ToolResultStatus::kNotFound);
    EXPECT_EQ(tool.Providers().Unregister(ProviderId("unknown")).status,
              ToolResultStatus::kNotFound);
    EXPECT_EQ(tool.Providers().GetProvider(ProviderId("unknown")).status,
              ToolResultStatus::kNotFound);
}

TEST(ToolFailure, TOL_092_InvocationPreparationUnknownCapability) {
    Tool tool(ToolId("fail-tool-3"),
              ToolConfiguration{"failure", "1.0", "failure test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    ASSERT_TRUE(tool.Activate().Succeeded());
    const InvocationPreparationResult result =
        tool.InvocationPreparation().PrepareInvocation(
            InvocationRequest{CapabilityId("unknown"), "req", "payload"});
    EXPECT_EQ(result.status, InvocationPreparationStatus::kNotFound);
}

TEST(ToolFailure, TOL_093_ProviderCallbackFailureNormalized) {
    // DescribeCapabilities raising during registration is
    // normalized to kRejected; the Provider is not registered
    // and no state is mutated (TOL-093, TOL-065).
    Tool tool(ToolId("fail-tool-4"),
              ToolConfiguration{"failure", "1.0", "failure test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    auto provider = std::make_unique<test::TestToolProvider>("provider-a");
    provider->throw_on_describe = true;
    const ProviderResult registered =
        tool.Providers().Register(std::move(provider));
    EXPECT_EQ(registered.status, ToolResultStatus::kRejected);
    EXPECT_EQ(tool.Providers().GetProvider(ProviderId("provider-a")).status,
              ToolResultStatus::kNotFound);

    // PrepareInvocation raising is normalized to kRejected; the
    // Tool state is unchanged.
    auto provider2 = std::make_unique<test::TestToolProvider>("provider-a");
    provider2->capabilities.push_back(
        test::MakeCapability("cap-a", "provider-a"));
    ASSERT_EQ(tool.Providers().Register(std::move(provider2)).status,
              ToolResultStatus::kSuccess);
    ASSERT_TRUE(tool.Activate().Succeeded());

    // fetch the registered view to toggle behavior
    const ProviderViewResult view =
        tool.Providers().GetProvider(ProviderId("provider-a"));
    ASSERT_EQ(view.status, ToolResultStatus::kSuccess);
    static_cast<test::TestToolProvider*>(view.provider)->throw_on_prepare = true;
    const InvocationPreparationResult prepared =
        tool.InvocationPreparation().PrepareInvocation(
            InvocationRequest{CapabilityId("cap-a"), "req", "payload"});
    EXPECT_EQ(prepared.status, InvocationPreparationStatus::kRejected);
    EXPECT_EQ(tool.Capabilities().Get(CapabilityId("cap-a")).status,
              ToolResultStatus::kSuccess);
}

TEST(ToolFailure, TOL_069_EquivalentInvalidInputsProduceSameCategory) {
    Tool tool(ToolId("fail-tool-5"),
              ToolConfiguration{"failure", "1.0", "failure test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    const auto first = tool.Discovery().FindCapability(CapabilityId("missing"));
    const auto second = tool.Discovery().FindCapability(CapabilityId("missing"));
    EXPECT_EQ(first.status, second.status);
    EXPECT_EQ(first.status, ToolResultStatus::kNotFound);

    const auto dup1 = tool.Capabilities().RegisterCapability(
        test::MakeCapability("cap-a", "provider-a"));
    ASSERT_EQ(dup1.status, ToolResultStatus::kSuccess);
    const auto dup2 = tool.Capabilities().RegisterCapability(
        test::MakeCapability("cap-a", "provider-a"));
    const auto dup3 = tool.Capabilities().RegisterCapability(
        test::MakeCapability("cap-a", "provider-a"));
    EXPECT_EQ(dup2.status, dup3.status);
    EXPECT_EQ(dup2.status, ToolResultStatus::kAlreadyExists);
}

TEST(ToolFailure, TOL_070_NoHiddenRecoveryForFailedOperations) {
    Tool tool(ToolId("fail-tool-6"),
              ToolConfiguration{"failure", "1.0", "failure test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    ASSERT_EQ(tool.Capabilities().RegisterCapability(
                  test::MakeCapability("cap-a", "provider-a"))
                  .status,
              ToolResultStatus::kSuccess);
    // A failed replacement of an unknown capability must not
    // substitute or redirect (TOL-070).
    const auto failed = tool.Capabilities().ReplaceCapability(
        test::MakeCapability("other-cap", "provider-a"));
    EXPECT_EQ(failed.status, ToolResultStatus::kNotFound);
    const auto fetched = tool.Capabilities().Get(CapabilityId("cap-a"));
    ASSERT_EQ(fetched.status, ToolResultStatus::kSuccess);
    EXPECT_EQ(fetched.capability->id, CapabilityId("cap-a"));
    EXPECT_EQ(fetched.capability->description, "description");
}

TEST(ToolFailure, TOL_088_FailedPostRetiredOperationHasNoSideEffect) {
    Tool tool(ToolId("fail-tool-7"),
              ToolConfiguration{"failure", "1.0", "failure test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    ASSERT_EQ(tool.Capabilities().RegisterCapability(
                  test::MakeCapability("cap-a", "provider-a"))
                  .status,
              ToolResultStatus::kSuccess);
    ASSERT_TRUE(tool.Activate().Succeeded());
    ASSERT_TRUE(tool.Retire().Succeeded());
    ASSERT_TRUE(tool.FinalizeRetirement().Succeeded());
    EXPECT_EQ(tool.Capabilities().RegisterCapability(
                  test::MakeCapability("cap-b", "provider-a"))
                  .status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(tool.Discovery().ListCapabilities().status,
              ToolResultStatus::kUnavailable);
}

}  // namespace
}  // namespace ak::tool