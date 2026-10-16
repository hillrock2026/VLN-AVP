// ============================================================
// tool_registration_test.cpp - P1-IS006 Rev2 Chapter 33.5
// ============================================================
// Registration tests: single-Tool cardinality (TOL-081),
// lifecycle registration transition (TOL-021), duplicate
// capability/Provider registration rejection (TOL-042),
// lifecycle gating (TOL-020), and no mutation on rejected
// registration (TOL-042, TOL-065).
// ============================================================

#include <agent_kernel/tool/tool.hpp>

#include <gtest/gtest.h>

#include <memory>
#include <string>
#include <type_traits>

#include "test_doubles.hpp"

namespace ak::tool {
namespace {

// Negative surface: no multi-Tool registration or enumeration
// exists on the Tool root (TOL-081, TOL-083).
template <typename T, typename = void>
struct HasRegisterTool : std::false_type {};
template <typename T>
struct HasRegisterTool<T, std::void_t<decltype(std::declval<T&>().RegisterTool(
                              std::declval<ToolId>()))>> : std::true_type {};

template <typename T, typename = void>
struct HasListTools : std::false_type {};
template <typename T>
struct HasListTools<T, std::void_t<decltype(std::declval<T&>().ListTools())>>
    : std::true_type {};

TEST(ToolRegistration, TOL_081_SingleToolRootHasExactlyOneIdentity) {
    static_assert(!HasRegisterTool<Tool>::value,
                  "Tool root must not expose a multi-Tool RegisterTool surface");
    static_assert(!HasListTools<Tool>::value,
                  "Tool root must not expose a multi-Tool ListTools surface");

    Tool tool(ToolId("single-tool"),
              ToolConfiguration{"registration", "1.0", ""});
    // The identity is fixed at construction and cannot change.
    EXPECT_EQ(tool.Id(), ToolId("single-tool"));
    EXPECT_EQ(tool.Id().Value(), "single-tool");
    // No second Tool identity is addressable through the root.
    EXPECT_EQ(tool.Discovery().ListCapabilities().capabilities.size(), 0u);
}

TEST(ToolRegistration, TOL_021_LifecycleRegistrationTransition) {
    Tool tool(ToolId("registration-tool"),
              ToolConfiguration{"registration", "1.0", ""});
    EXPECT_FALSE(tool.Registration().IsRegistered());
    const ToolLifecycleResult result = tool.Registration().Register();
    EXPECT_TRUE(result.Succeeded());
    EXPECT_TRUE(tool.Registration().IsRegistered());
    EXPECT_TRUE(tool.LifecycleState() == ToolLifecycleState::kRegistered);
}

TEST(ToolRegistration, TOL_042_DuplicateCapabilityRegistrationRejected) {
    Tool tool(ToolId("registration-tool-2"),
              ToolConfiguration{"registration", "1.0", ""});
    ASSERT_TRUE(tool.Register().Succeeded());
    const auto first = tool.Capabilities().RegisterCapability(
        test::MakeCapability("cap-1", "provider-a"));
    ASSERT_EQ(first.status, ToolResultStatus::kSuccess);
    const auto duplicate = tool.Capabilities().RegisterCapability(
        test::MakeCapability("cap-1", "provider-a"));
    EXPECT_EQ(duplicate.status, ToolResultStatus::kAlreadyExists);

    // The existing registration is not mutated by the rejected
    // duplicate (TOL-042, TOL-065).
    const auto fetched = tool.Capabilities().Get(CapabilityId("cap-1"));
    ASSERT_EQ(fetched.status, ToolResultStatus::kSuccess);
    EXPECT_EQ(fetched.capability->id, CapabilityId("cap-1"));
    EXPECT_EQ(fetched.capability->provider, ProviderId("provider-a"));
}

TEST(ToolRegistration, TOL_042_DuplicateProviderRegistrationRejected) {
    Tool tool(ToolId("registration-tool-3"),
              ToolConfiguration{"registration", "1.0", ""});
    ASSERT_TRUE(tool.Register().Succeeded());
    auto first = std::make_unique<test::TestToolProvider>("provider-a");
    ASSERT_EQ(tool.Providers().Register(std::move(first)).status,
              ToolResultStatus::kSuccess);
    auto duplicate = std::make_unique<test::TestToolProvider>("provider-a");
    EXPECT_EQ(tool.Providers().Register(std::move(duplicate)).status,
              ToolResultStatus::kAlreadyExists);
    // Only the original Provider is registered.
    EXPECT_EQ(tool.Providers().GetProvider(ProviderId("provider-a")).status,
              ToolResultStatus::kSuccess);
}

TEST(ToolRegistration, TOL_042_DuplicateLifecycleRegistrationRejected) {
    Tool tool(ToolId("registration-tool-4"),
              ToolConfiguration{"registration", "1.0", ""});
    ASSERT_TRUE(tool.Register().Succeeded());
    const ToolLifecycleResult duplicate = tool.Register();
    EXPECT_EQ(duplicate.status, ToolLifecycleResultStatus::kInvalidState);
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kRegistered);
}

TEST(ToolRegistration, TOL_020_CapabilityAndProviderRegistrationGatedInInitializing) {
    Tool tool(ToolId("registration-tool-5"),
              ToolConfiguration{"registration", "1.0", ""});
    EXPECT_EQ(tool.Capabilities().RegisterCapability(
                  test::MakeCapability("cap-1", "provider-a"))
                  .status,
              ToolResultStatus::kUnavailable);
    auto provider = std::make_unique<test::TestToolProvider>("provider-a");
    EXPECT_EQ(tool.Providers().Register(std::move(provider)).status,
              ToolResultStatus::kUnavailable);
}

TEST(ToolRegistration, TOL_065_RejectedProviderRegistrationMutatesNothing) {
    Tool tool(ToolId("registration-tool-6"),
              ToolConfiguration{"registration", "1.0", ""});
    ASSERT_TRUE(tool.Register().Succeeded());
    auto first = std::make_unique<test::TestToolProvider>("provider-a");
    ASSERT_EQ(tool.Providers().Register(std::move(first)).status,
              ToolResultStatus::kSuccess);
    // Rejected duplicate (same id) must not remove the first.
    auto duplicate = std::make_unique<test::TestToolProvider>("provider-a");
    EXPECT_EQ(tool.Providers().Register(std::move(duplicate)).status,
              ToolResultStatus::kAlreadyExists);
    EXPECT_EQ(tool.Providers().GetProvider(ProviderId("provider-a")).status,
              ToolResultStatus::kSuccess);
}

TEST(ToolRegistration, TOL_042_ProviderRegistrationPublishesDescribedCapabilities) {
    Tool tool(ToolId("registration-tool-7"),
              ToolConfiguration{"registration", "1.0", ""});
    ASSERT_TRUE(tool.Register().Succeeded());
    auto provider = std::make_unique<test::TestToolProvider>("provider-a");
    provider->capabilities.push_back(
        test::MakeCapability("described-1", "provider-a"));
    provider->capabilities.push_back(
        test::MakeCapability("described-2", "provider-a"));
    ASSERT_EQ(tool.Providers().Register(std::move(provider)).status,
              ToolResultStatus::kSuccess);
    const auto discovery = tool.Discovery().ListCapabilities();
    ASSERT_EQ(discovery.status, ToolResultStatus::kSuccess);
    EXPECT_EQ(discovery.capabilities.size(), 2u);
    EXPECT_EQ(discovery.capabilities[0].id, CapabilityId("described-1"));
    EXPECT_EQ(discovery.capabilities[1].id, CapabilityId("described-2"));
    // Described capabilities are bound to the registering
    // Provider (the architectural source).
    EXPECT_EQ(discovery.capabilities[0].provider, ProviderId("provider-a"));
}

TEST(ToolRegistration, TOL_082_RegistrationStatePersistsThroughLifecycle) {
    Tool tool(ToolId("registration-tool-8"),
              ToolConfiguration{"registration", "1.0", ""});
    ASSERT_TRUE(tool.Register().Succeeded());
    ASSERT_TRUE(tool.Activate().Succeeded());
    ASSERT_TRUE(tool.Retire().Succeeded());
    ASSERT_TRUE(tool.FinalizeRetirement().Succeeded());
    // The noexcept state accessor reports the truth after
    // retirement (TOL-082); result-bearing service operations
    // return the deterministic refusal (verified in
    // tool_services_test.cpp).
    EXPECT_TRUE(tool.Registration().IsRegistered());
}

}  // namespace
}  // namespace ak::tool