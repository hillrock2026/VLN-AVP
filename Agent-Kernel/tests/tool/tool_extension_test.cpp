// ============================================================
// tool_extension_test.cpp - P1-IS006 Rev2 Chapter 33.11
// ============================================================
// Extension tests: extension ownership (TOL-061), extension
// context contract (TOL-085), attach/detach ownership
// (TOL-103), extension boundary invariants (TOL-062), and
// post-kRetired refusal (TOL-088).
// ============================================================

#include <agent_kernel/tool/tool.hpp>

#include <gtest/gtest.h>

#include <memory>
#include <string>
#include <type_traits>

#include "test_doubles.hpp"

namespace ak::tool {
namespace {

// The extension context SHALL NOT expose lifecycle mutation,
// Agent-facing coordination, or Runtime operations (TOL-085,
// TOL-062).
template <typename T, typename = void>
struct HasContextRegister : std::false_type {};
template <typename T>
struct HasContextRegister<
    T, std::void_t<decltype(std::declval<T&>().Register())>> : std::true_type {};

template <typename T, typename = void>
struct HasContextActivate : std::false_type {};
template <typename T>
struct HasContextActivate<
    T, std::void_t<decltype(std::declval<T&>().Activate())>> : std::true_type {};

template <typename T, typename = void>
struct HasScheduleWork : std::false_type {};
template <typename T>
struct HasScheduleWork<
    T, std::void_t<decltype(std::declval<T&>().ScheduleWork())>>
    : std::true_type {};

TEST(ToolExtension, TOL_061_ExtensionOwnershipTransfersToTool) {
    Tool tool(ToolId("ext-tool"),
              ToolConfiguration{"ext", "1.0", "extension test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    auto extension = std::make_unique<test::TestToolExtension>("ext-a");
    const ExtensionResult result =
        tool.Extensions().RegisterExtension(std::move(extension));
    ASSERT_EQ(result.status, ToolResultStatus::kSuccess);
    // Exclusive ownership transferred.
    EXPECT_EQ(extension.get(), nullptr);
    EXPECT_TRUE(tool.Extensions().IsAttached("ext-a"));
}

TEST(ToolExtension, TOL_103_AttachInvokedWithToolOwnedContext) {
    Tool tool(ToolId("ext-tool-2"),
              ToolConfiguration{"ext", "1.0", "extension test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    auto extension = std::make_unique<test::TestToolExtension>("ext-a");
    test::TestToolExtension* raw = extension.get();
    ASSERT_EQ(tool.Extensions().RegisterExtension(std::move(extension)).status,
              ToolResultStatus::kSuccess);
    EXPECT_EQ(raw->attach_count, 1u);
    ASSERT_NE(raw->attached_tool_id, nullptr);
    EXPECT_EQ(*raw->attached_tool_id, ToolId("ext-tool-2"));
}

TEST(ToolExtension, TOL_103_DetachAndDestructionOwnedByTool) {
    Tool tool(ToolId("ext-tool-3"),
              ToolConfiguration{"ext", "1.0", "extension test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    bool destroyed = false;
    auto extension = std::make_unique<test::TestToolExtension>("ext-a");
    test::TestToolExtension* raw = extension.get();
    extension->destroyed = &destroyed;
    ASSERT_EQ(tool.Extensions().RegisterExtension(std::move(extension)).status,
              ToolResultStatus::kSuccess);
    EXPECT_FALSE(destroyed);
    EXPECT_TRUE(tool.Extensions().IsAttached("ext-a"));

    const ExtensionResult unregistered =
        tool.Extensions().UnregisterExtension("ext-a");
    ASSERT_EQ(unregistered.status, ToolResultStatus::kSuccess);
    // Detach was invoked and the extension was destroyed before
    // UnregisterExtension returned (TOL-103).
    EXPECT_EQ(raw->detach_count, 1u);
    EXPECT_TRUE(destroyed);
    EXPECT_FALSE(tool.Extensions().IsAttached("ext-a"));
}

TEST(ToolExtension, TOL_103_DuplicateNameRejectedWithoutMutation) {
    Tool tool(ToolId("ext-tool-4"),
              ToolConfiguration{"ext", "1.0", "extension test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    auto first = std::make_unique<test::TestToolExtension>("ext-a");
    ASSERT_EQ(tool.Extensions().RegisterExtension(std::move(first)).status,
              ToolResultStatus::kSuccess);
    auto duplicate = std::make_unique<test::TestToolExtension>("ext-a");
    const ExtensionResult rejected =
        tool.Extensions().RegisterExtension(std::move(duplicate));
    EXPECT_EQ(rejected.status, ToolResultStatus::kAlreadyExists);
    // The rejected duplicate must not mutate the existing
    // extension state (TOL-103, TOL-065).
    EXPECT_TRUE(tool.Extensions().IsAttached("ext-a"));
}

TEST(ToolExtension, TOL_092_UnknownExtensionNameNotFound) {
    Tool tool(ToolId("ext-tool-5"),
              ToolConfiguration{"ext", "1.0", "extension test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    EXPECT_EQ(tool.Extensions().UnregisterExtension("missing").status,
              ToolResultStatus::kNotFound);
    EXPECT_FALSE(tool.Extensions().IsAttached("missing"));
}

TEST(ToolExtension, TOL_085_ExtensionContextExposesNoLifecycleMutation) {
    static_assert(!HasContextRegister<IToolExtensionContext>::value,
                  "Extension context must not expose lifecycle Register");
    static_assert(!HasContextActivate<IToolExtensionContext>::value,
                  "Extension context must not expose lifecycle Activate");
    static_assert(!HasScheduleWork<IToolExtensionContext>::value,
                  "Extension context must not expose Runtime scheduling");
}

TEST(ToolExtension, TOL_062_ExtensionCannotBecomeRuntime) {
    Tool tool(ToolId("ext-tool-6"),
              ToolConfiguration{"ext", "1.0", "extension test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    // The context exposes capability and Provider services
    // only; a real attach round-trip proves the extension can
    // read Tool-owned state without acquiring authority.
    auto extension = std::make_unique<test::TestToolExtension>("ext-a");
    extension->attach_hook = [](IToolExtensionContext& context) {
        EXPECT_EQ(context.Id().Value(), "ext-tool-6");
        EXPECT_EQ(context.LifecycleState(), ToolLifecycleState::kRegistered);
        EXPECT_EQ(context.OperationalState(), ToolOperationalState::kRegistered);
        // Capability/Provider services are reachable.
        IToolCapabilityService& capabilities = context.Capabilities();
        IToolProviderService& providers = context.Providers();
        (void)capabilities;
        (void)providers;
    };
    ASSERT_EQ(tool.Extensions().RegisterExtension(std::move(extension)).status,
              ToolResultStatus::kSuccess);
}

TEST(ToolExtension, TOL_088_ExtensionMutationRefusedAfterRetired) {
    Tool tool(ToolId("ext-tool-7"),
              ToolConfiguration{"ext", "1.0", "extension test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    ASSERT_TRUE(tool.Activate().Succeeded());
    ASSERT_TRUE(tool.Retire().Succeeded());
    ASSERT_TRUE(tool.FinalizeRetirement().Succeeded());
    EXPECT_EQ(tool.Extensions().RegisterExtension(
                  std::make_unique<test::TestToolExtension>("ext-a"))
                  .status,
              ToolResultStatus::kUnavailable);
    EXPECT_EQ(tool.Extensions().UnregisterExtension("ext-a").status,
              ToolResultStatus::kUnavailable);
}

TEST(ToolExtension, TOL_065_AttachFailureMutatesNothing) {
    Tool tool(ToolId("ext-tool-8"),
              ToolConfiguration{"ext", "1.0", "extension test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    auto extension = std::make_unique<test::TestToolExtension>("ext-a");
    extension->throw_on_attach = true;
    const ExtensionResult rejected =
        tool.Extensions().RegisterExtension(std::move(extension));
    EXPECT_EQ(rejected.status, ToolResultStatus::kRejected);
    EXPECT_FALSE(tool.Extensions().IsAttached("ext-a"));
}

}  // namespace
}  // namespace ak::tool