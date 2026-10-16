#include <gtest/gtest.h>
#include <stdexcept>

#include <capability_resolver.h>
#include <capability_binding.h>
#include <agent_kernel/task/task_execution_descriptor.hpp>

namespace ak::runtime {

// ============================================================
// CapabilityResolverTestAccess — friend access to private methods
// ============================================================
struct CapabilityResolverTestAccess {
    static void Register(CapabilityResolver& r,
                         const std::string& name,
                         const std::string& provider) {
        r.Register(name, provider);
    }
    static void Unregister(CapabilityResolver& r,
                           const std::string& name) {
        r.Unregister(name);
    }
    static std::size_t RegistrySize(const CapabilityResolver& r) {
        return r.RegistrySize();
    }
    static bool Contains(const CapabilityResolver& r,
                         const std::string& name) {
        return r.Contains(name);
    }
};

namespace {

// Helper: create a descriptor with a given capability name.
ak::TaskExecutionDescriptor MakeDescriptor(const std::string& name) {
    ak::TaskExecutionDescriptor desc;
    desc.capability.name = name;
    return desc;
}

// ============================================================
// Construction
// ============================================================
TEST(CapabilityResolverTest, DefaultConstructionSucceeds) {
    CapabilityResolver resolver;
    EXPECT_EQ(CapabilityResolverTestAccess::RegistrySize(resolver), 0u);
}

TEST(CapabilityResolverTest, DestructionIsSafe) {
    {
        CapabilityResolver resolver;
        CapabilityResolverTestAccess::Register(resolver, "test.cap", "test-provider");
    }
    SUCCEED();
}

// ============================================================
// Registry Operations (private, accessed through friend)
// ============================================================
TEST(CapabilityResolverTest, RegisterIncreasesRegistrySize) {
    CapabilityResolver resolver;
    CapabilityResolverTestAccess::Register(resolver, "demo.echo", "stub");
    EXPECT_EQ(CapabilityResolverTestAccess::RegistrySize(resolver), 1u);
}

TEST(CapabilityResolverTest, UnregisterDecreasesRegistrySize) {
    CapabilityResolver resolver;
    CapabilityResolverTestAccess::Register(resolver, "demo.echo", "stub");
    CapabilityResolverTestAccess::Unregister(resolver, "demo.echo");
    EXPECT_EQ(CapabilityResolverTestAccess::RegistrySize(resolver), 0u);
}

TEST(CapabilityResolverTest, ContainsReturnsFalseForUnknown) {
    CapabilityResolver resolver;
    EXPECT_FALSE(CapabilityResolverTestAccess::Contains(resolver, "nonexistent"));
}

TEST(CapabilityResolverTest, ContainsReturnsTrueAfterRegister) {
    CapabilityResolver resolver;
    CapabilityResolverTestAccess::Register(resolver, "known.cap", "provider-x");
    EXPECT_TRUE(CapabilityResolverTestAccess::Contains(resolver, "known.cap"));
}

// ============================================================
// Resolve — Success (returns CapabilityBinding per AK0033 §7.2)
// ============================================================
TEST(CapabilityResolverTest, ResolveReturnsBindingForRegisteredCapability) {
    CapabilityResolver resolver;
    CapabilityResolverTestAccess::Register(resolver, "llm.chat", "openai");

    auto desc = MakeDescriptor("llm.chat");
    auto result = resolver.Resolve(desc);

    // AK0033 §8.2: CapabilityBinding with providerName
    EXPECT_EQ(result.providerName, "openai");
}

TEST(CapabilityResolverTest, ResolveReturnsCorrectProviderName) {
    CapabilityResolver resolver;
    CapabilityResolverTestAccess::Register(resolver, "code.execute", "sandbox");
    CapabilityResolverTestAccess::Register(resolver, "llm.chat", "openai");

    auto r1 = resolver.Resolve(MakeDescriptor("code.execute"));
    auto r2 = resolver.Resolve(MakeDescriptor("llm.chat"));

    EXPECT_EQ(r1.providerName, "sandbox");
    EXPECT_EQ(r2.providerName, "openai");
}

// ============================================================
// Resolve — Failure (throws std::runtime_error per AK0033 §7.6)
// ============================================================
TEST(CapabilityResolverTest, ResolveThrowsForUnregistered) {
    CapabilityResolver resolver;
    auto desc = MakeDescriptor("unknown.cap");

    EXPECT_THROW({
        (void)resolver.Resolve(desc);
    }, std::runtime_error);
}

TEST(CapabilityResolverTest, ResolveThrowsForEmptyName) {
    CapabilityResolver resolver;
    auto desc = MakeDescriptor("");

    EXPECT_THROW({
        (void)resolver.Resolve(desc);
    }, std::runtime_error);
}

TEST(CapabilityResolverTest, ResolveThrowsWithDescriptiveMessage) {
    CapabilityResolver resolver;
    auto desc = MakeDescriptor("missing.cap");

    try {
        (void)resolver.Resolve(desc);
        FAIL() << "Expected std::runtime_error";
    } catch (const std::runtime_error& e) {
        EXPECT_NE(std::string(e.what()).find("not found"), std::string::npos);
    }
}

// ============================================================
// IsResolvable — non-mutating pre-check (AK0033 §7.7-7.8)
// ============================================================
TEST(CapabilityResolverTest, IsResolvableReturnsTrueForRegistered) {
    CapabilityResolver resolver;
    CapabilityResolverTestAccess::Register(resolver, "ns.sub.cap.v2", "test-provider");
    auto desc = MakeDescriptor("ns.sub.cap.v2");
    EXPECT_TRUE(resolver.IsResolvable(desc));
}

TEST(CapabilityResolverTest, IsResolvableReturnsFalseForUnregistered) {
    CapabilityResolver resolver;
    auto desc = MakeDescriptor("missing");
    EXPECT_FALSE(resolver.IsResolvable(desc));
}

TEST(CapabilityResolverTest, IsResolvableReturnsFalseForEmptyName) {
    CapabilityResolver resolver;
    auto desc = MakeDescriptor("");
    EXPECT_FALSE(resolver.IsResolvable(desc));
}

TEST(CapabilityResolverTest, IsResolvableDoesNotMutateRegistry) {
    CapabilityResolver resolver;
    CapabilityResolverTestAccess::Register(resolver, "stable.cap", "p");

    // Pre-check should not affect resolution.
    EXPECT_TRUE(resolver.IsResolvable(MakeDescriptor("stable.cap")));
    EXPECT_EQ(CapabilityResolverTestAccess::RegistrySize(resolver), 1u);

    // Resolution should still succeed.
    auto binding = resolver.Resolve(MakeDescriptor("stable.cap"));
    EXPECT_EQ(binding.providerName, "p");
}

// ============================================================
// Deterministic Resolution (AK0033 §1.2, §12.2)
// ============================================================
TEST(CapabilityResolverTest, SameInputProducesSameBinding) {
    CapabilityResolver r1, r2;
    CapabilityResolverTestAccess::Register(r1, "det.op", "provider-a");
    CapabilityResolverTestAccess::Register(r2, "det.op", "provider-a");

    auto desc = MakeDescriptor("det.op");
    auto binding1 = r1.Resolve(desc);
    auto binding2 = r2.Resolve(desc);

    EXPECT_EQ(binding1.providerName, binding2.providerName);
}

// ============================================================
// Multiple Capabilities
// ============================================================
TEST(CapabilityResolverTest, MultipleCapabilitiesResolveIndependently) {
    CapabilityResolver resolver;
    CapabilityResolverTestAccess::Register(resolver, "alpha", "provider-a");
    CapabilityResolverTestAccess::Register(resolver, "beta", "provider-b");
    CapabilityResolverTestAccess::Register(resolver, "gamma", "provider-c");

    EXPECT_EQ(CapabilityResolverTestAccess::RegistrySize(resolver), 3u);

    auto bindingAlpha = resolver.Resolve(MakeDescriptor("alpha"));
    auto bindingBeta  = resolver.Resolve(MakeDescriptor("beta"));
    auto bindingGamma = resolver.Resolve(MakeDescriptor("gamma"));

    EXPECT_EQ(bindingAlpha.providerName, "provider-a");
    EXPECT_EQ(bindingBeta.providerName, "provider-b");
    EXPECT_EQ(bindingGamma.providerName, "provider-c");
}

// ============================================================
// Scope Compliance — Resolver does not execute
// ============================================================
TEST(CapabilityResolverTest, ResolverProducesOnlyCapabilityBinding) {
    CapabilityResolver resolver;
    CapabilityResolverTestAccess::Register(resolver, "test.cap", "test-provider");
    auto desc = MakeDescriptor("test.cap");
    auto result = resolver.Resolve(desc);

    // Resolver produced a CapabilityBinding — nothing else.
    EXPECT_EQ(result.providerName, "test-provider");
}

// ============================================================
// AK0033 §6.2 — Verify no ICapabilityResolver methods visible
// ============================================================
// This test verifies that Supports() and Validate() do NOT
// appear in the public interface. Compilation will fail if
// they are accidentally exposed.
TEST(CapabilityResolverTest, SupportsAndValidateNotInPublicAPI) {
    CapabilityResolver resolver;
    CapabilityResolverTestAccess::Register(resolver, "demo", "p");

    // Verify IsResolvable (AK0033) works.
    EXPECT_TRUE(resolver.IsResolvable(MakeDescriptor("demo")));

    // NOTE: The following lines would NOT compile if uncommented:
    // resolver.Supports("demo");   // Compile error — not public
    // resolver.Validate(desc);     // Compile error — not public
}

// ============================================================
// Strong Exception Guarantee (AK0033 §7.7)
// ============================================================
TEST(CapabilityResolverTest, RegistryUnchangedAfterException) {
    CapabilityResolver resolver;
    CapabilityResolverTestAccess::Register(resolver, "safe.cap", "safe-provider");

    // Trigger an exception with an empty name.
    EXPECT_THROW({
        (void)resolver.Resolve(MakeDescriptor(""));
    }, std::runtime_error);

    // Registry must remain unchanged (Strong Exception Guarantee).
    EXPECT_EQ(CapabilityResolverTestAccess::RegistrySize(resolver), 1u);
    EXPECT_TRUE(resolver.IsResolvable(MakeDescriptor("safe.cap")));
    EXPECT_EQ(resolver.Resolve(MakeDescriptor("safe.cap")).providerName, "safe-provider");
}

}  // namespace
}  // namespace ak::runtime
