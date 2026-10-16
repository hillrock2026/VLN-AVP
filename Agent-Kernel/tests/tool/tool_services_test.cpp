// ============================================================
// tool_services_test.cpp - P1-IS006 Rev2 Chapter 33.8
// ============================================================
// Service tests: every Tool Service against the lifecycle/
// availability matrix (Chapter 31, TOL-077), including
// kRetiring per-operation availability (TOL-087), post-kRetired
// deterministic refusal (TOL-088), and the Restricted row
// (TOL-098).
// ============================================================

#include <agent_kernel/tool/tool.hpp>

#include <gtest/gtest.h>

#include <memory>
#include <string>

#include "test_doubles.hpp"

namespace ak::tool {
namespace {

// Brings a tool to the requested lifecycle state with one
// capability and one Provider registered where the state allows
// registration.
struct MatrixTool {
    explicit MatrixTool(ToolLifecycleState target) : ok(Initialize(target)) {}

    // Builds the capability/Provider set in kRegistered so that
    // later lifecycle states observe the same storage. No GTest
    // assertion is used inside the constructor.
    bool Initialize(ToolLifecycleState target) {
        if (!tool.Register().Succeeded()) {
            return false;
        }
        auto provider = std::make_unique<test::TestToolProvider>("provider-a");
        provider->capabilities.push_back(
            test::MakeCapability("cap-a", "provider-a"));
        if (tool.Providers().Register(std::move(provider)).status !=
            ToolResultStatus::kSuccess) {
            return false;
        }
        if (tool.Capabilities()
                .RegisterCapability(test::MakeCapability(
                    "constrained-cap", "provider-a",
                    CapabilityAvailability::kAvailable,
                    /*constrained=*/true))
                .status != ToolResultStatus::kSuccess) {
            return false;
        }
        switch (target) {
            case ToolLifecycleState::kRegistered:
                return true;
            case ToolLifecycleState::kAvailable:
                return tool.Activate().Succeeded();
            case ToolLifecycleState::kSuspended:
                return tool.Activate().Succeeded() && tool.Suspend().Succeeded();
            case ToolLifecycleState::kRetiring:
                return tool.Activate().Succeeded() && tool.Retire().Succeeded();
            case ToolLifecycleState::kRetired:
                return tool.Activate().Succeeded() && tool.Retire().Succeeded() &&
                       tool.FinalizeRetirement().Succeeded();
            default:
                return false;
        }
    }

    Tool tool{ToolId("matrix-tool"),
              ToolConfiguration{"matrix", "1.0", "matrix test"}};
    bool ok = false;
};
TEST(ToolServices, TOL_077_MatrixRowInitializing) {
    Tool tool(ToolId("matrix-init"),
              ToolConfiguration{"matrix", "1.0", "matrix test"});
    EXPECT_EQ(tool.Discovery().ListCapabilities().status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(tool.Capabilities().Get(CapabilityId("cap-a")).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(tool.Capabilities().RegisterCapability(
                  test::MakeCapability("cap-a", "provider-a"))
                  .status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(tool.Availability().GetAvailability(CapabilityId("cap-a")).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(tool.Availability().IsToolAvailable().status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(tool.Permissions().Check(CapabilityId("cap-a"), {}).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(tool.Providers().GetProvider(ProviderId("provider-a")).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(tool.Providers().ProviderFor(CapabilityId("cap-a")).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(tool.InvocationPreparation()
                  .PrepareInvocation(
                      InvocationRequest{CapabilityId("cap-a"), "req", "p"})
                  .status,
              InvocationPreparationStatus::kUnavailable);
    // Lifecycle Register() is the only available operation.
    EXPECT_TRUE(tool.Register().Succeeded());
}

TEST(ToolServices, TOL_077_MatrixRowRegistered) {
    MatrixTool matrix(ToolLifecycleState::kRegistered);
    ASSERT_TRUE(matrix.ok) << "MatrixTool setup failed";
    EXPECT_EQ(matrix.tool.Discovery().ListCapabilities().status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Capabilities().Get(CapabilityId("cap-a")).status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Capabilities().GetContract(CapabilityId("cap-a")).status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Availability().GetAvailability(CapabilityId("cap-a")).status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Availability().IsToolAvailable().status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Permissions().Check(CapabilityId("cap-a"), {}).status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Providers().GetProvider(ProviderId("provider-a")).status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Providers().ProviderFor(CapabilityId("cap-a")).status,
              ToolResultStatus::kSuccess);
    // Invocation preparation is unavailable until kAvailable.
    EXPECT_EQ(matrix.tool.InvocationPreparation()
                  .PrepareInvocation(
                      InvocationRequest{CapabilityId("cap-a"), "req", "p"})
                  .status,
              InvocationPreparationStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Register().status,
              ToolLifecycleResultStatus::kInvalidState);
}

TEST(ToolServices, TOL_077_MatrixRowAvailable) {
    MatrixTool matrix(ToolLifecycleState::kAvailable);
    ASSERT_TRUE(matrix.ok) << "MatrixTool setup failed";
    EXPECT_EQ(matrix.tool.Discovery().ListCapabilities().status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Capabilities().Get(CapabilityId("cap-a")).status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Availability().GetAvailability(CapabilityId("cap-a")).status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Permissions().Check(CapabilityId("cap-a"), {}).status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Providers().GetProvider(ProviderId("provider-a")).status,
              ToolResultStatus::kSuccess);
    // Unconstrained capability preparation succeeds.
    EXPECT_EQ(matrix.tool.InvocationPreparation()
                  .PrepareInvocation(
                      InvocationRequest{CapabilityId("cap-a"), "req", "p"})
                  .status,
              InvocationPreparationStatus::kPrepared);
}

TEST(ToolServices, TOL_077_MatrixRowSuspended) {
    MatrixTool matrix(ToolLifecycleState::kSuspended);
    ASSERT_TRUE(matrix.ok) << "MatrixTool setup failed";
    EXPECT_EQ(matrix.tool.Discovery().ListCapabilities().status,
              ToolResultStatus::kSuccess);
    // Capability reads are unavailable while suspended.
    EXPECT_EQ(matrix.tool.Capabilities().Get(CapabilityId("cap-a")).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Capabilities().GetContract(CapabilityId("cap-a")).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Capabilities().ReplaceCapability(
                  test::MakeCapability("cap-a", "provider-a"))
                  .status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Availability().GetAvailability(CapabilityId("cap-a")).status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Permissions().Check(CapabilityId("cap-a"), {}).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Providers().GetProvider(ProviderId("provider-a")).status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Providers().Unregister(ProviderId("provider-a")).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.InvocationPreparation()
                  .PrepareInvocation(
                      InvocationRequest{CapabilityId("cap-a"), "req", "p"})
                  .status,
              InvocationPreparationStatus::kUnavailable);
}

TEST(ToolServices, TOL_087_RetiringReadsAvailableMutationsUnavailable) {
    MatrixTool matrix(ToolLifecycleState::kRetiring);
    ASSERT_TRUE(matrix.ok) << "MatrixTool setup failed";
    // Reads remain available in kRetiring.
    EXPECT_EQ(matrix.tool.Discovery().ListCapabilities().status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Capabilities().Get(CapabilityId("cap-a")).status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Availability().GetAvailability(CapabilityId("cap-a")).status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Permissions().Check(CapabilityId("cap-a"), {}).status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Providers().GetProvider(ProviderId("provider-a")).status,
              ToolResultStatus::kSuccess);
    // No new Tool capability operation is accepted after the
    // retirement transition is committed (TOL-087).
    EXPECT_EQ(matrix.tool.Capabilities().RegisterCapability(
                  test::MakeCapability("new-cap", "provider-a"))
                  .status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Capabilities().ReplaceCapability(
                  test::MakeCapability("cap-a", "provider-a"))
                  .status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Providers().Register(
                  std::make_unique<test::TestToolProvider>("provider-b"))
                  .status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Providers().Unregister(ProviderId("provider-a")).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.InvocationPreparation()
                  .PrepareInvocation(
                      InvocationRequest{CapabilityId("cap-a"), "req", "p"})
                  .status,
              InvocationPreparationStatus::kUnavailable);
    // The only legal lifecycle operation is FinalizeRetirement.
    EXPECT_EQ(matrix.tool.Activate().status,
              ToolLifecycleResultStatus::kInvalidState);
    EXPECT_TRUE(matrix.tool.FinalizeRetirement().Succeeded());
}

TEST(ToolServices, TOL_088_PostRetiredServicesReturnDeterministicRefusal) {
    MatrixTool matrix(ToolLifecycleState::kRetired);
    ASSERT_TRUE(matrix.ok) << "MatrixTool setup failed";
    EXPECT_EQ(matrix.tool.Discovery().ListCapabilities().status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Discovery().FindCapability(CapabilityId("cap-a")).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Capabilities().Get(CapabilityId("cap-a")).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Capabilities().GetContract(CapabilityId("cap-a")).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Capabilities().RegisterCapability(
                  test::MakeCapability("cap-b", "provider-a"))
                  .status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Capabilities().ReplaceCapability(
                  test::MakeCapability("cap-a", "provider-a"))
                  .status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Availability().GetAvailability(CapabilityId("cap-a")).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Availability().IsToolAvailable().status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Permissions().Check(CapabilityId("cap-a"), {}).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Providers().GetProvider(ProviderId("provider-a")).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Providers().ProviderFor(CapabilityId("cap-a")).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Providers().Register(
                  std::make_unique<test::TestToolProvider>("provider-b"))
                  .status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Providers().Unregister(ProviderId("provider-a")).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.InvocationPreparation()
                  .PrepareInvocation(
                      InvocationRequest{CapabilityId("cap-a"), "req", "p"})
                  .status,
              InvocationPreparationStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Extensions().RegisterExtension(
                  std::make_unique<test::TestToolExtension>("ext"))
                  .status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.Extensions().UnregisterExtension("ext").status,
              ToolResultStatus::kUnavailable);
    EXPECT_FALSE(matrix.tool.Extensions().IsAttached("ext"));
    // Service references remain valid and the refusal has no
    // side effects (TOL-088, TOL-078).
    EXPECT_EQ(matrix.tool.LifecycleState(), ToolLifecycleState::kRetired);
}

TEST(ToolServices, TOL_098_RestrictedRowBehavesPerLifecycleMatrix) {
    MatrixTool matrix(ToolLifecycleState::kAvailable);
    ASSERT_TRUE(matrix.ok) << "MatrixTool setup failed";
    // constrained-cap is constrained, so the operational state
    // is kRestricted (TOL-095).
    EXPECT_EQ(matrix.tool.OperationalState(), ToolOperationalState::kRestricted);
    // Invocation preparation for the constrained capability is
    // unavailable; unconstrained follows the lifecycle matrix.
    EXPECT_EQ(matrix.tool.InvocationPreparation()
                  .PrepareInvocation(InvocationRequest{
                      CapabilityId("constrained-cap"), "req", "p"})
                  .status,
              InvocationPreparationStatus::kUnavailable);
    EXPECT_EQ(matrix.tool.InvocationPreparation()
                  .PrepareInvocation(
                      InvocationRequest{CapabilityId("cap-a"), "req", "p"})
                  .status,
              InvocationPreparationStatus::kPrepared);
    // Discovery, capability lookup, availability, permission
    // and Provider reads follow the matrix.
    EXPECT_EQ(matrix.tool.Discovery().ListCapabilities().status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Capabilities().Get(CapabilityId("cap-a")).status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Availability().GetAvailability(CapabilityId("cap-a")).status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Permissions().Check(CapabilityId("cap-a"), {}).status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(matrix.tool.Providers().GetProvider(ProviderId("provider-a")).status,
              ToolResultStatus::kSuccess);
}

TEST(ToolServices, TOL_053_ServiceReferencesOutliveRetirement) {
    // References returned before retirement remain valid after
    // retirement and refuse deterministically (TOL-053).
    Tool tool(ToolId("matrix-life"),
              ToolConfiguration{"matrix", "1.0", "matrix test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    IToolDiscoveryService& discovery = tool.Discovery();
    IToolRegistrationService& registration = tool.Registration();
    IToolCapabilityService& capabilities = tool.Capabilities();
    IToolAvailabilityService& availability = tool.Availability();
    IToolPermissionService& permissions = tool.Permissions();
    IToolProviderService& providers = tool.Providers();
    IToolInvocationPreparationService& preparation =
        tool.InvocationPreparation();
    IToolExtensionService& extensions = tool.Extensions();
    ASSERT_TRUE(tool.Activate().Succeeded());
    ASSERT_TRUE(tool.Retire().Succeeded());
    ASSERT_TRUE(tool.FinalizeRetirement().Succeeded());
    EXPECT_EQ(discovery.ListCapabilities().status, ToolResultStatus::kUnavailable);
    EXPECT_EQ(registration.Register().status,
              ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(capabilities.Get(CapabilityId("cap-a")).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(availability.GetAvailability(CapabilityId("cap-a")).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(permissions.Check(CapabilityId("cap-a"), {}).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(providers.GetProvider(ProviderId("provider-a")).status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(preparation
                  .PrepareInvocation(
                      InvocationRequest{CapabilityId("cap-a"), "req", "p"})
                  .status,
              InvocationPreparationStatus::kUnavailable);
    EXPECT_EQ(extensions.IsAttached("ext"), false);
}

}  // namespace
}  // namespace ak::tool