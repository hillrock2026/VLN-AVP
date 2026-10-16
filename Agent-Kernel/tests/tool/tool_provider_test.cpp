// ============================================================
// tool_provider_test.cpp - P1-IS006 Rev2 Chapter 33.7
// ============================================================
// Provider tests: Provider ownership (TOL-039, TOL-099),
// capability description, availability, invocation
// preparation, lifetime and destruction (TOL-100), and the
// no-Runtime-execution surface (TOL-038).
// ============================================================

#include <agent_kernel/tool/tool.hpp>

#include <gtest/gtest.h>

#include <memory>
#include <string>
#include <type_traits>

#include "test_doubles.hpp"

namespace ak::tool {
namespace {

template <typename T, typename = void>
struct HasExecute : std::false_type {};
template <typename T>
struct HasExecute<T, std::void_t<decltype(std::declval<T&>().Execute())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasSchedule : std::false_type {};
template <typename T>
struct HasSchedule<T, std::void_t<decltype(std::declval<T&>().Schedule())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasResolveRuntimeCapability : std::false_type {};
template <typename T>
struct HasResolveRuntimeCapability<
    T, std::void_t<decltype(std::declval<T&>().ResolveRuntimeCapability())>>
    : std::true_type {};

TEST(ToolProvider, TOL_099_ProviderOwnershipTransfersToTool) {
    Tool tool(ToolId("provider-tool"),
              ToolConfiguration{"provider", "1.0", ""});
    ASSERT_TRUE(tool.Register().Succeeded());
    auto provider = std::make_unique<test::TestToolProvider>("provider-a");
    const ProviderId id = provider->Id();
    const auto result = tool.Providers().Register(std::move(provider));
    ASSERT_EQ(result.status, ToolResultStatus::kSuccess);
    ASSERT_TRUE(result.provider_id.has_value());
    EXPECT_EQ(*result.provider_id, id);
    // Exclusive ownership transferred: the caller no longer
    // holds the Provider.
    EXPECT_EQ(provider.get(), nullptr);
}

TEST(ToolProvider, TOL_099_GetProviderReturnsNonOwningView) {
    Tool tool(ToolId("provider-tool-2"),
              ToolConfiguration{"provider", "1.0", ""});
    ASSERT_TRUE(tool.Register().Succeeded());
    auto provider = std::make_unique<test::TestToolProvider>("provider-a");
    const ProviderId id = provider->Id();
    ASSERT_EQ(tool.Providers().Register(std::move(provider)).status,
              ToolResultStatus::kSuccess);
    const ProviderViewResult view =
        tool.Providers().GetProvider(ProviderId("provider-a"));
    ASSERT_EQ(view.status, ToolResultStatus::kSuccess);
    ASSERT_NE(view.provider, nullptr);
    EXPECT_EQ(view.provider->Id(), id);
}

TEST(ToolProvider, TOL_100_UnregisterDestroysProviderBeforeReturning) {
    Tool tool(ToolId("provider-tool-3"),
              ToolConfiguration{"provider", "1.0", ""});
    ASSERT_TRUE(tool.Register().Succeeded());
    bool destroyed = false;
    auto provider = std::make_unique<test::TestToolProvider>("provider-a");
    provider->destroyed = &destroyed;
    ASSERT_EQ(tool.Providers().Register(std::move(provider)).status,
              ToolResultStatus::kSuccess);
    EXPECT_FALSE(destroyed);
    const auto unregistered = tool.Providers().Unregister(ProviderId("provider-a"));
    ASSERT_EQ(unregistered.status, ToolResultStatus::kSuccess);
    // Destroyed before Unregister returns (TOL-100).
    EXPECT_TRUE(destroyed);
    // The view is no longer valid.
    EXPECT_EQ(tool.Providers().GetProvider(ProviderId("provider-a")).status,
              ToolResultStatus::kNotFound);
}

TEST(ToolProvider, TOL_100_ProviderDestroyedAtToolDestruction) {
    bool destroyed = false;
    {
        Tool tool(ToolId("provider-tool-4"),
                  ToolConfiguration{"provider", "1.0", ""});
        ASSERT_TRUE(tool.Register().Succeeded());
        auto provider = std::make_unique<test::TestToolProvider>("provider-a");
        provider->destroyed = &destroyed;
        ASSERT_EQ(tool.Providers().Register(std::move(provider)).status,
                  ToolResultStatus::kSuccess);
        EXPECT_FALSE(destroyed);
    }
    EXPECT_TRUE(destroyed);
}

TEST(ToolProvider, ProviderCapabilityDescriptionIsPublished) {
    Tool tool(ToolId("provider-tool-5"),
              ToolConfiguration{"provider", "1.0", ""});
    ASSERT_TRUE(tool.Register().Succeeded());
    auto provider = std::make_unique<test::TestToolProvider>("provider-a");
    provider->capabilities.push_back(
        test::MakeCapability("cap-a", "provider-a"));
    provider->capabilities.push_back(
        test::MakeCapability("cap-b", "provider-a"));
    ASSERT_EQ(tool.Providers().Register(std::move(provider)).status,
              ToolResultStatus::kSuccess);
    const auto discovery = tool.Discovery().ListCapabilities();
    ASSERT_EQ(discovery.status, ToolResultStatus::kSuccess);
    ASSERT_EQ(discovery.capabilities.size(), 2u);
    // The Provider view allows capability description reads.
    const ProviderViewResult view =
        tool.Providers().GetProvider(ProviderId("provider-a"));
    ASSERT_EQ(view.status, ToolResultStatus::kSuccess);
    const auto described = view.provider->DescribeCapabilities();
    EXPECT_EQ(described.size(), 2u);
}

TEST(ToolProvider, TOL_092_ProviderUnavailableRejectsPreparation) {
    Tool tool(ToolId("provider-tool-6"),
              ToolConfiguration{"provider", "1.0", ""});
    ASSERT_TRUE(tool.Register().Succeeded());
    auto provider =
        std::make_unique<test::TestToolProvider>("provider-a", /*available=*/false);
    provider->capabilities.push_back(
        test::MakeCapability("cap-a", "provider-a"));
    ASSERT_EQ(tool.Providers().Register(std::move(provider)).status,
              ToolResultStatus::kSuccess);
    ASSERT_TRUE(tool.Activate().Succeeded());
    const auto prepared = tool.InvocationPreparation().PrepareInvocation(
        InvocationRequest{CapabilityId("cap-a"), "req-1", "payload"});
    EXPECT_EQ(prepared.status, InvocationPreparationStatus::kRejected);
}

TEST(ToolProvider, InvocationPreparationReturnsProviderToken) {
    Tool tool(ToolId("provider-tool-7"),
              ToolConfiguration{"provider", "1.0", ""});
    ASSERT_TRUE(tool.Register().Succeeded());
    auto provider = std::make_unique<test::TestToolProvider>("provider-a");
    provider->capabilities.push_back(
        test::MakeCapability("cap-a", "provider-a"));
    ASSERT_EQ(tool.Providers().Register(std::move(provider)).status,
              ToolResultStatus::kSuccess);
    ASSERT_TRUE(tool.Activate().Succeeded());
    const auto prepared = tool.InvocationPreparation().PrepareInvocation(
        InvocationRequest{CapabilityId("cap-a"), "req-1", "payload"});
    ASSERT_EQ(prepared.status, InvocationPreparationStatus::kPrepared);
    EXPECT_EQ(prepared.capability_id, CapabilityId("cap-a"));
    EXPECT_EQ(prepared.provider_id, ProviderId("provider-a"));
    EXPECT_EQ(prepared.invocation_token, "prepared-token");
}

TEST(ToolProvider, TOL_038_ProviderCannotExecuteRuntimeWork) {
    static_assert(!HasExecute<IToolProvider>::value,
                  "IToolProvider must not expose Execute");
    static_assert(!HasSchedule<IToolProvider>::value,
                  "IToolProvider must not expose Schedule");
    static_assert(!HasResolveRuntimeCapability<IToolProvider>::value,
                  "IToolProvider must not resolve Runtime capabilities");
    static_assert(!HasExecute<IToolProviderService>::value,
                  "Provider Service must not expose Execute");
    static_assert(!HasResolveRuntimeCapability<IToolProviderService>::value,
                  "Provider Service must not resolve Runtime capabilities");
}

}  // namespace
}  // namespace ak::tool