// ============================================================
// agent_tool_binding_test.cpp - P1-IS006 Rev2 Chapter 33.9
// ============================================================
// Agent boundary tests: non-owning binding (TOL-054), state
// forwarding without a second lifecycle authority (TOL-055),
// capability access, discovery, invocation preparation,
// lifecycle forwarding, no public host Tool() accessor
// (TOL-084), and the unchanged P1-IS002 IToolContract /
// AgentCoordinationService surface (TOL-086) with byte-identical
// coordination headers.
// ============================================================

#include <agent_kernel/agent/coordination/agent_coordination_service.hpp>
#include <agent_kernel/agent/coordination/i_tool_contract.hpp>
#include <agent_kernel/agent_tool/agent_tool_binding.hpp>
#include <agent_kernel/agent_tool/agent_tool_host.hpp>
#include <agent_kernel/tool/tool.hpp>

#include <gtest/gtest.h>

#include <fstream>
#include <sstream>
#include <string>
#include <string_view>
#include <type_traits>
#include <vector>

#include "../tool/test_doubles.hpp"

namespace ak::agent {
namespace {

// ------------------------------------------------------------
// Negative surface traits
// ------------------------------------------------------------

template <typename T, typename = void>
struct HasToolAccessor : std::false_type {};
template <typename T>
struct HasToolAccessor<
    T, std::void_t<decltype(std::declval<T&>().Tool())>> : std::true_type {};

template <typename T, typename = void>
struct HasListTools : std::false_type {};
template <typename T>
struct HasListTools<T, std::void_t<decltype(std::declval<T&>().ListTools())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasScheduleWork : std::false_type {};
template <typename T>
struct HasScheduleWork<
    T, std::void_t<decltype(std::declval<T&>().ScheduleWork())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasExecuteWork : std::false_type {};
template <typename T>
struct HasExecuteWork<
    T, std::void_t<decltype(std::declval<T&>().ExecuteWork())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasSubmitRuntimeRequest : std::false_type {};
template <typename T>
struct HasSubmitRuntimeRequest<
    T, std::void_t<decltype(std::declval<T&>().SubmitRuntimeRequest())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasPublishRuntimeEvent : std::false_type {};
template <typename T>
struct HasPublishRuntimeEvent<
    T, std::void_t<decltype(std::declval<T&>().PublishRuntimeEvent())>>
    : std::true_type {};

// IToolContract (P1-IS002) SHALL NOT carry Tool capability,
// lifecycle, or invocation semantics (TOL-086).
template <typename T, typename = void>
struct HasToolRegister : std::false_type {};
template <typename T>
struct HasToolRegister<
    T, std::void_t<decltype(std::declval<T&>().Register())>> : std::true_type {};

template <typename T, typename = void>
struct HasPrepareInvocation : std::false_type {};
template <typename T>
struct HasPrepareInvocation<
    T, std::void_t<decltype(std::declval<T&>().PrepareInvocation(
           std::declval<const ak::tool::InvocationRequest&>()))>>
    : std::true_type {};

template <typename T, typename = void>
struct HasGetCapability : std::false_type {};
template <typename T>
struct HasGetCapability<
    T, std::void_t<decltype(std::declval<T&>().GetCapability(
           std::declval<const ak::tool::CapabilityId&>()))>>
    : std::true_type {};

// ------------------------------------------------------------
// Byte-identical P1-IS002 baseline verification (TOL-086)
// ------------------------------------------------------------

std::string ReadFile(const std::string& path) {
    std::ifstream stream(path, std::ios::binary);
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return buffer.str();
}

TEST(AgentToolBinding, TOL_086_CoordinationHeadersAreByteIdenticalToBaseline) {
    const char* names[] = {
        "subsystem_contract.hpp", "i_context_contract.hpp",
        "i_memory_contract.hpp",  "i_planner_contract.hpp",
        "i_tool_contract.hpp",    "agent_coordination_service.hpp"};
    const std::string include_root = AK_INCLUDE_ROOT;
    const std::string baseline_root =
        std::string(AK_INCLUDE_ROOT) + "/../tests/agent_tool/baseline_coordination";
    for (const char* name : names) {
        const std::string live =
            include_root + "/agent_kernel/agent/coordination/" + name;
        const std::string baseline = baseline_root + "/" + name;
        const std::string live_content = ReadFile(live);
        const std::string baseline_content = ReadFile(baseline);
        EXPECT_EQ(live_content, baseline_content)
            << "coordination header " << name
            << " is not byte-identical to the P1-IS002 baseline (TOL-086)";
    }
}

// ------------------------------------------------------------
// Binding behavior
// ------------------------------------------------------------

TEST(AgentToolBinding, TOL_054_BindingIsNonOwning) {
    ak::tool::Tool tool(ak::tool::ToolId("binding-tool"),
              ak::tool::ToolConfiguration{"binding", "1.0", ""});
    {
        AgentToolBinding binding(tool);
        EXPECT_EQ(&binding.Id(), &tool.Id());
    }
    // The Tool outlives the binding; the binding owned nothing.
    EXPECT_EQ(tool.Id().Value(), "binding-tool");
}

TEST(AgentToolBinding, TOL_055_BindingForwardsStateWithoutSecondAuthority) {
    ak::tool::Tool tool(ak::tool::ToolId("binding-tool-2"),
              ak::tool::ToolConfiguration{"binding", "1.0", ""});
    AgentToolBinding binding(tool);
    EXPECT_EQ(binding.LifecycleState(), tool.LifecycleState());
    EXPECT_EQ(binding.OperationalState(), tool.OperationalState());
    ASSERT_TRUE(binding.Register().Succeeded());
    EXPECT_EQ(binding.LifecycleState(), tool.LifecycleState());
    EXPECT_EQ(binding.OperationalState(), tool.OperationalState());
    ASSERT_TRUE(binding.Activate().Succeeded());
    EXPECT_EQ(binding.LifecycleState(), tool.LifecycleState());
    EXPECT_EQ(binding.OperationalState(), tool.OperationalState());
}

TEST(AgentToolBinding, TOL_055_LifecycleForwardingReturnsToolResults) {
    ak::tool::Tool tool(ak::tool::ToolId("binding-tool-3"),
              ak::tool::ToolConfiguration{"binding", "1.0", ""});
    AgentToolBinding binding(tool);
    const auto registered = binding.Register();
    EXPECT_TRUE(registered.Succeeded());
    EXPECT_EQ(registered.state, tool.Register().state);  // kInvalidState now
    EXPECT_EQ(registered.state, ak::tool::ToolLifecycleState::kRegistered);
    const auto activated = binding.Activate();
    EXPECT_TRUE(activated.Succeeded());
    const auto suspended = binding.Suspend();
    EXPECT_TRUE(suspended.Succeeded());
    const auto resumed = binding.Resume();
    EXPECT_TRUE(resumed.Succeeded());
    const auto retired = binding.Retire();
    EXPECT_TRUE(retired.Succeeded());
    const auto finalized = binding.FinalizeRetirement();
    EXPECT_TRUE(finalized.Succeeded());
    EXPECT_EQ(binding.LifecycleState(), ak::tool::ToolLifecycleState::kRetired);
}

TEST(AgentToolBinding, TOL_055_CapabilityDiscoveryAndPreparationForward) {
    ak::tool::Tool tool(ak::tool::ToolId("binding-tool-4"),
              ak::tool::ToolConfiguration{"binding", "1.0", ""});
    ASSERT_TRUE(tool.Register().Succeeded());
    auto provider = std::make_unique<ak::tool::test::TestToolProvider>("provider-a");
    provider->capabilities.push_back(ak::tool::test::MakeCapability(
        "cap-a", "provider-a"));
    ASSERT_EQ(tool.Providers().Register(std::move(provider)).status,
              ak::tool::ToolResultStatus::kSuccess);
    ASSERT_TRUE(tool.Activate().Succeeded());

    AgentToolBinding binding(tool);
    const auto discovered = binding.Discover();
    ASSERT_EQ(discovered.status, ak::tool::ToolResultStatus::kSuccess);
    ASSERT_EQ(discovered.capabilities.size(), 1u);
    EXPECT_EQ(discovered.capabilities[0].id, ak::tool::CapabilityId("cap-a"));

    const auto capability = binding.GetCapability(ak::tool::CapabilityId("cap-a"));
    ASSERT_EQ(capability.status, ak::tool::ToolResultStatus::kSuccess);
    EXPECT_EQ(capability.capability->provider, ak::tool::ProviderId("provider-a"));

    const auto prepared = binding.PrepareInvocation(
        ak::tool::InvocationRequest{ak::tool::CapabilityId("cap-a"),
                                    "req-1", "payload"});
    EXPECT_EQ(prepared.status, ak::tool::InvocationPreparationStatus::kPrepared);
    EXPECT_EQ(prepared.invocation_token, "prepared-token");
}

TEST(AgentToolBinding, TOL_055_UnknownCapabilityIsNotFoundThroughBinding) {
    ak::tool::Tool tool(ak::tool::ToolId("binding-tool-5"),
              ak::tool::ToolConfiguration{"binding", "1.0", ""});
    ASSERT_TRUE(tool.Register().Succeeded());
    AgentToolBinding binding(tool);
    EXPECT_EQ(binding.GetCapability(ak::tool::CapabilityId("missing")).status,
              ak::tool::ToolResultStatus::kNotFound);
    EXPECT_EQ(binding.Discover().status, ak::tool::ToolResultStatus::kSuccess);
    EXPECT_EQ(binding.Discover().capabilities.size(), 0u);
}

TEST(AgentToolBinding, TOL_084_HostExposesNoPublicToolAccessor) {
    static_assert(!HasToolAccessor<AgentToolHost>::value,
                  "AgentToolHost must not expose a public Tool() accessor");
}

TEST(AgentToolBinding, TOL_056_BindingIsTheSoleAgentToolSurface) {
    static_assert(!HasListTools<AgentToolBinding>::value);
    static_assert(!HasScheduleWork<AgentToolBinding>::value);
    static_assert(!HasExecuteWork<AgentToolBinding>::value);
    static_assert(!HasSubmitRuntimeRequest<AgentToolBinding>::value);
    static_assert(!HasPublishRuntimeEvent<AgentToolBinding>::value);
}

TEST(AgentToolBinding, TOL_086_IToolContractCarriesNoToolSemantics) {
    static_assert(!HasToolRegister<ak::agent::IToolContract>::value,
                  "IToolContract must not carry Tool lifecycle semantics");
    static_assert(!HasPrepareInvocation<ak::agent::IToolContract>::value,
                  "IToolContract must not carry invocation semantics");
    static_assert(!HasGetCapability<ak::agent::IToolContract>::value,
                  "IToolContract must not carry capability semantics");
    static_assert(!HasListTools<ak::agent::IToolContract>::value);
}

TEST(AgentToolBinding, TOL_086_AgentCoordinationServiceBindsToolContract) {
    // The Phase 1 generic coordination acknowledgment surface
    // remains exactly as approved in P1-IS002.
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
    const CoordinationResult result = coordination.CoordinateTool();
    EXPECT_TRUE(result.accepted);
    EXPECT_EQ(coordination.CoordinatedSubsystemCount(), 1u);
}

}  // namespace
}  // namespace ak::agent