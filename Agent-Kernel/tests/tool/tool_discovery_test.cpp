// ============================================================
// tool_discovery_test.cpp - P1-IS006 Rev2 Chapter 33.6
// ============================================================
// Discovery tests: capability listing scoped to the owning
// Tool root only (TOL-083), lookup with kNotFound (TOL-092),
// no multi-Tool enumeration surface (TOL-083), no planning
// behavior (TOL-044), and matrix enforcement (TOL-077).
// ============================================================

#include <agent_kernel/tool/tool.hpp>

#include <gtest/gtest.h>

#include <string>
#include <type_traits>

#include "test_doubles.hpp"

namespace ak::tool {
namespace {

template <typename T, typename = void>
struct HasListTools : std::false_type {};
template <typename T>
struct HasListTools<T, std::void_t<decltype(std::declval<T&>().ListTools())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasPlanTypes : std::false_type {};
template <typename T>
struct HasPlanTypes<
    T, std::void_t<decltype(std::declval<T&>().capabilities[0].plan_topology)>>
    : std::true_type {};

TEST(ToolDiscovery, TOL_083_DiscoveryScopesToOwningToolOnly) {
    Tool tool_a(ToolId("discovery-a"),
                ToolConfiguration{"discovery", "1.0", ""});
    Tool tool_b(ToolId("discovery-b"),
                ToolConfiguration{"discovery", "1.0", ""});
    ASSERT_TRUE(tool_a.Register().Succeeded());
    ASSERT_TRUE(tool_b.Register().Succeeded());
    ASSERT_EQ(tool_a.Capabilities().RegisterCapability(
                  test::MakeCapability("cap-a", "provider-a"))
                  .status,
              ToolResultStatus::kSuccess);
    ASSERT_EQ(tool_b.Capabilities().RegisterCapability(
                  test::MakeCapability("cap-b", "provider-b"))
                  .status,
              ToolResultStatus::kSuccess);

    const auto discovery_a = tool_a.Discovery().ListCapabilities();
    ASSERT_EQ(discovery_a.status, ToolResultStatus::kSuccess);
    ASSERT_EQ(discovery_a.capabilities.size(), 1u);
    EXPECT_EQ(discovery_a.capabilities[0].id, CapabilityId("cap-a"));
    // Tool B cannot see Tool A's capabilities.
    EXPECT_EQ(tool_b.Capabilities().Get(CapabilityId("cap-a")).status,
              ToolResultStatus::kNotFound);
    EXPECT_EQ(tool_a.Capabilities().Get(CapabilityId("cap-b")).status,
              ToolResultStatus::kNotFound);
}

TEST(ToolDiscovery, TOL_083_NoMultiToolEnumerationSurface) {
    static_assert(!HasListTools<Tool>::value,
                  "Tool must not expose a multi-Tool ListTools surface");
    static_assert(!HasListTools<IToolDiscoveryService>::value,
                  "Discovery must not expose a multi-Tool enumeration surface");
}

TEST(ToolDiscovery, TOL_092_FindCapabilityUnknownReturnsNotFound) {
    Tool tool(ToolId("discovery-tool"),
              ToolConfiguration{"discovery", "1.0", ""});
    ASSERT_TRUE(tool.Register().Succeeded());
    const auto result =
        tool.Discovery().FindCapability(CapabilityId("unknown-cap"));
    EXPECT_EQ(result.status, ToolResultStatus::kNotFound);
    EXPECT_FALSE(result.capability.has_value());
}

TEST(ToolDiscovery, TOL_044_DiscoveryReturnsCapabilityInformationOnly) {
    static_assert(!HasPlanTypes<ToolDiscoveryResult>::value,
                  "Discovery result must not carry planning types");
    Tool tool(ToolId("discovery-tool-2"),
              ToolConfiguration{"discovery", "1.0", ""});
    ASSERT_TRUE(tool.Register().Succeeded());
    ASSERT_EQ(tool.Capabilities().RegisterCapability(
                  test::MakeCapability("cap-a", "provider-a"))
                  .status,
              ToolResultStatus::kSuccess);
    const auto discovery = tool.Discovery().ListCapabilities();
    ASSERT_EQ(discovery.status, ToolResultStatus::kSuccess);
    ASSERT_EQ(discovery.capabilities.size(), 1u);
    // Only Tool-owned capability information is returned.
    EXPECT_EQ(discovery.capabilities[0].id, CapabilityId("cap-a"));
    EXPECT_EQ(discovery.capabilities[0].description, "description");
    EXPECT_EQ(discovery.capabilities[0].provider, ProviderId("provider-a"));
}

TEST(ToolDiscovery, TOL_077_DiscoveryEnforcesLifecycleMatrix) {
    Tool tool(ToolId("discovery-tool-3"),
              ToolConfiguration{"discovery", "1.0", ""});
    // kInitializing: discovery unavailable.
    EXPECT_EQ(tool.Discovery().ListCapabilities().status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(tool.Discovery().FindCapability(CapabilityId("cap-a")).status,
              ToolResultStatus::kUnavailable);
    // kRegistered: discovery available.
    ASSERT_TRUE(tool.Register().Succeeded());
    EXPECT_EQ(tool.Discovery().ListCapabilities().status,
              ToolResultStatus::kSuccess);
    // kRetired: discovery unavailable.
    ASSERT_TRUE(tool.Activate().Succeeded());
    ASSERT_TRUE(tool.Retire().Succeeded());
    ASSERT_TRUE(tool.FinalizeRetirement().Succeeded());
    EXPECT_EQ(tool.Discovery().ListCapabilities().status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(tool.Discovery().FindCapability(CapabilityId("cap-a")).status,
              ToolResultStatus::kUnavailable);
}

}  // namespace
}  // namespace ak::tool