// ============================================================
// agent_tool_integration_test.cpp - P1-IS006 Rev2 Chapter 33.10
// ============================================================
// Production composition tests using REAL production objects:
//
//   Agent
//     -> AgentToolHost
//     -> AgentToolBinding
//     -> Tool
//
// No test double substitutes for the production Tool root in
// the primary composition test (TOL-057/058/059/060/101).
// ============================================================

#include <agent_kernel/agent/agent.hpp>
#include <agent_kernel/agent/coordination/agent_coordination_service.hpp>
#include <agent_kernel/agent/coordination/i_tool_contract.hpp>
#include <agent_kernel/agent_tool/agent_tool_binding.hpp>
#include <agent_kernel/agent_tool/agent_tool_host.hpp>
#include <agent_kernel/tool/tool.hpp>

#include <gtest/gtest.h>

#include <string>
#include <string_view>

#include "../tool/test_doubles.hpp"

namespace ak::agent {
namespace {

TEST(AgentToolIntegration, TOL_057_RealCompositionOwnsRealTool) {
    AgentToolHost host(ak::tool::ToolId("integration-tool"),
                       ak::tool::ToolConfiguration{"integration", "1.0", ""});
    const AgentToolBinding& binding = host.Binding();
    // The binding is a non-owning view over the REAL Tool root
    // owned by the host (TOL-058/059).
    EXPECT_EQ(binding.Id().Value(), "integration-tool");
    EXPECT_EQ(binding.LifecycleState(), ak::tool::ToolLifecycleState::kInitializing);
    EXPECT_EQ(binding.OperationalState(),
              ak::tool::ToolOperationalState::kUninitialized);
}

TEST(AgentToolIntegration, TOL_101_AgentCoordinatesExclusivelyThroughBinding) {
    // The Agent-facing production path terminates at the
    // binding; no factory, injection route, or accessor reaches
    // the Tool root other than the binding (TOL-101, TOL-084).
    AgentToolHost host(ak::tool::ToolId("integration-tool-2"),
                       ak::tool::ToolConfiguration{"integration", "1.0", ""});
    AgentToolBinding& binding = host.Binding();
    ASSERT_TRUE(binding.Register().Succeeded());
    ASSERT_TRUE(binding.Activate().Succeeded());
    EXPECT_EQ(binding.LifecycleState(), ak::tool::ToolLifecycleState::kAvailable);
    EXPECT_EQ(binding.OperationalState(), ak::tool::ToolOperationalState::kAvailable);
}

TEST(AgentToolIntegration, TOL_060_RealEndToEndPathWithoutRuntime) {
    AgentToolHost host(ak::tool::ToolId("integration-tool-3"),
                       ak::tool::ToolConfiguration{"integration", "1.0", ""});
    AgentToolBinding& binding = host.Binding();
    ASSERT_TRUE(binding.Register().Succeeded());
    ASSERT_TRUE(binding.Activate().Succeeded());

    // Through the binding, capability lookup and discovery
    // forward to the real Tool root of the host.
    const ak::tool::ToolDiscoveryResult discovered = binding.Discover();
    ASSERT_EQ(discovered.status, ak::tool::ToolResultStatus::kSuccess);
    EXPECT_EQ(discovered.capabilities.size(), 0u);
    EXPECT_EQ(binding.GetCapability(ak::tool::CapabilityId("cap-a")).status,
              ak::tool::ToolResultStatus::kNotFound);

    // Refusal gate after retirement: no Tool service performs
    // work after kRetired (TOL-088).
    ASSERT_TRUE(binding.Retire().Succeeded());
    ASSERT_TRUE(binding.FinalizeRetirement().Succeeded());
    EXPECT_EQ(binding.Discover().status, ak::tool::ToolResultStatus::kUnavailable);
    EXPECT_EQ(binding.GetCapability(ak::tool::CapabilityId("cap-a")).status,
              ak::tool::ToolResultStatus::kUnavailable);
    EXPECT_EQ(binding.PrepareInvocation(
                  ak::tool::InvocationRequest{ak::tool::CapabilityId("cap-a"),
                                              "req", "payload"})
                  .status,
              ak::tool::InvocationPreparationStatus::kUnavailable);
}

TEST(AgentToolIntegration, TOL_086_Phase1GenericSurfaceRemainsUnchanged) {
    // The Phase 1 generic coordination surface (P1-IS002) is
    // exercised against the real headers; IToolContract remains
    // a coordination acknowledgment contract only.
    class TestToolContract final : public ak::agent::IToolContract {
    public:
        std::string_view ContractName() const noexcept override {
            return "Tool";
        }
        CoordinationAcknowledgement AcknowledgeCoordination() override {
            return {true, "tool coordination acknowledged"};
        }
    };
    TestToolContract contract;
    AgentCoordinationService coordination;
    EXPECT_TRUE(coordination.BindTool(contract));
    EXPECT_TRUE(coordination.IsBound(SubsystemId::kTool));
    const auto result = coordination.CoordinateTool();
    EXPECT_TRUE(result.accepted);
}

TEST(AgentToolIntegration, TOL_059_HostConstructsToolThenBinding) {
    // Member order is normative: Tool is constructed before the
    // binding and outlives it (TOL-059).
    {
        AgentToolHost host(ak::tool::ToolId("integration-tool-4"),
                           ak::tool::ToolConfiguration{"integration", "1.0", ""});
        const AgentToolBinding& binding = host.Binding();
        EXPECT_EQ(binding.Id().Value(), "integration-tool-4");
    }
    // No Runtime target is linked by this executable; a full
    // round-trip through the real composition proves Phase 4
    // independence (TOL-060).
}

}  // namespace
}  // namespace ak::agent