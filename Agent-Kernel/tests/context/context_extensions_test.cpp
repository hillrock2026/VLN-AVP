// ============================================================
// context_extensions_test.cpp - P1-IS004 extension-boundary
// conformance
// ============================================================
// CTX-013: Context extensions remain Context-owned; foreign
// subsystem extensions (Agent/Memory/Planner/Tool/Unknown) are
// rejected; extensions cannot become cross-subsystem
// coordinators.
// ============================================================

#include <agent_kernel/context/context.hpp>
#include <agent_kernel/context/context_extensions.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "test_doubles.hpp"

namespace ak::context {
namespace {

ContextExtensionVersion MakeVersion() { return ContextExtensionVersion{1, 0}; }

TEST(ContextExtensions, ContextOwnedExtensionsAttach) {
    Context context(MakeContextIdentity(1));
    auto extension =
        std::make_shared<test::ContextExtensionDouble>("ctx-ext", MakeVersion());

    const ContextAttachResult attached = context.Extensions().Attach(extension);
    EXPECT_TRUE(attached.accepted);
    EXPECT_EQ(context.Extensions().Count(), 1);
    EXPECT_TRUE(context.Extensions().Contains("ctx-ext"));
    EXPECT_EQ(context.Extensions().GetState("ctx-ext"),
              ContextExtensionState::kAttached);

    // Context-owned extension lifecycle and configuration.
    EXPECT_TRUE(context.Extensions().Activate("ctx-ext"));
    EXPECT_EQ(context.Extensions().GetState("ctx-ext"),
              ContextExtensionState::kActive);
    EXPECT_TRUE(context.Extensions().Suspend("ctx-ext"));
    EXPECT_EQ(context.Extensions().GetState("ctx-ext"),
              ContextExtensionState::kSuspended);

    ak::KernelMetadata configuration;
    configuration.name = "config";
    EXPECT_TRUE(context.Extensions().SetConfiguration("ctx-ext", configuration));

    const std::vector<std::string> names = context.Extensions().Enumerate();
    ASSERT_EQ(names.size(), 1);
    EXPECT_EQ(names[0], "ctx-ext");
}

TEST(ContextExtensions, ForeignExtensionsAreRejected) {
    Context context(MakeContextIdentity(1));

    const ContextExtensionDomain foreign_domains[] = {
        ContextExtensionDomain::kAgent,
        ContextExtensionDomain::kMemory,
        ContextExtensionDomain::kPlanner,
        ContextExtensionDomain::kTool,
        ContextExtensionDomain::kUnknown};

    for (const ContextExtensionDomain domain : foreign_domains) {
        auto extension = std::make_shared<test::ContextExtensionDouble>(
            "foreign", MakeVersion(), domain);
        EXPECT_FALSE(context.Extensions().Attach(extension).accepted);
    }
    EXPECT_EQ(context.Extensions().Count(), 0);
    EXPECT_FALSE(context.Extensions().ContainsForeignExtension());

    // Null and duplicate extensions are rejected.
    EXPECT_FALSE(context.Extensions().Attach(nullptr).accepted);
    auto first =
        std::make_shared<test::ContextExtensionDouble>("dup", MakeVersion());
    EXPECT_TRUE(context.Extensions().Attach(first).accepted);
    auto duplicate =
        std::make_shared<test::ContextExtensionDouble>("dup", MakeVersion());
    EXPECT_FALSE(context.Extensions().Attach(duplicate).accepted);
}

TEST(ContextExtensions, DetachRemovesExtension) {
    Context context(MakeContextIdentity(1));
    context.Extensions().Attach(
        std::make_shared<test::ContextExtensionDouble>("ext", MakeVersion()));
    ASSERT_TRUE(context.Extensions().Contains("ext"));

    EXPECT_TRUE(context.Extensions().Detach("ext"));
    EXPECT_FALSE(context.Extensions().Contains("ext"));
    EXPECT_EQ(context.Extensions().Count(), 0);
    EXPECT_EQ(context.Extensions().GetState("ext"),
              ContextExtensionState::kDetached);
}

TEST(ContextExtensions, IntegrityAndCompatibilityAreContextGoverned) {
    Context context(MakeContextIdentity(1));
    context.Extensions().Attach(
        std::make_shared<test::ContextExtensionDouble>("good", MakeVersion()));
    context.Extensions().Attach(std::make_shared<test::ContextExtensionDouble>(
        "bad-version", ContextExtensionVersion{2, 0}));
    context.Extensions().Attach(std::make_shared<test::ContextExtensionDouble>(
        "bad-check", MakeVersion(), ContextExtensionDomain::kContext, false));

    EXPECT_FALSE(context.Extensions().ValidateIntegrity());
    EXPECT_FALSE(context.Extensions().ValidateCompatibility());

    ak::DiagnosticSink sink;
    context.Extensions().ValidateBoundary(sink);
    EXPECT_TRUE(sink.HasErrors());
}

TEST(ContextExtensions, ExtensionsDoNotBecomeCoordinators) {
    // The extension interface carries no peer or Runtime
    // coordination surface: it can only report name, domain,
    // version, and self-check status.
    static_assert(std::is_abstract_v<IContextExtension>);
    // A conforming boundary never contains a foreign extension.
    Context context(MakeContextIdentity(1));
    context.Extensions().Attach(
        std::make_shared<test::ContextExtensionDouble>("e", MakeVersion()));
    EXPECT_FALSE(context.Extensions().ContainsForeignExtension());
    EXPECT_TRUE(context.Extensions().ValidateIntegrity());
    EXPECT_TRUE(context.Extensions().ValidateCompatibility());
}

}  // namespace
}  // namespace ak::context
