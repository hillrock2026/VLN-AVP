// ============================================================
// memory_extensions_test.cpp - P1-IS003 extension conformance
// ============================================================
// MEM-013: Memory extensions attach only to Memory; Memory owns
// extension lifecycle, state, configuration, integrity,
// compatibility, and governance; foreign extensions are
// rejected.
// ============================================================

#include <agent_kernel/memory/memory.hpp>
#include <agent_kernel/memory/memory_extensions.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "test_doubles.hpp"

namespace ak::memory {
namespace {

MemoryExtensionVersion MakeVersion(std::uint32_t major,
                                   std::uint32_t minor = 0) {
    return MemoryExtensionVersion{major, minor};
}

TEST(MemoryExtensionBoundary, AttachesMemoryOwnedExtensions) {
    MemoryExtensionBoundary boundary;
    auto extension = std::make_shared<test::MemoryExtensionDouble>(
        "compression", MakeVersion(1, 2));

    const MemoryAttachResult result = boundary.Attach(extension);
    EXPECT_TRUE(result.accepted);
    EXPECT_EQ(boundary.Count(), 1);
    EXPECT_TRUE(boundary.Contains("compression"));

    const std::vector<std::string> names = boundary.Enumerate();
    ASSERT_EQ(names.size(), 1);
    EXPECT_EQ(names[0], "compression");
}

TEST(MemoryExtensionBoundary, RejectsDuplicateNames) {
    MemoryExtensionBoundary boundary;
    boundary.Attach(std::make_shared<test::MemoryExtensionDouble>(
        "dedup", MakeVersion(1, 0)));
    const MemoryAttachResult duplicate = boundary.Attach(
        std::make_shared<test::MemoryExtensionDouble>("dedup", MakeVersion(1, 0)));
    EXPECT_FALSE(duplicate.accepted);
    EXPECT_EQ(boundary.Count(), 1);
}

TEST(MemoryExtensionBoundary, ManagesExtensionLifecycleAndConfiguration) {
    MemoryExtensionBoundary boundary;
    boundary.Attach(std::make_shared<test::MemoryExtensionDouble>(
        "indexing", MakeVersion(1, 0)));

    EXPECT_EQ(boundary.GetState("indexing"), MemoryExtensionState::kAttached);
    EXPECT_TRUE(boundary.Activate("indexing"));
    EXPECT_EQ(boundary.GetState("indexing"), MemoryExtensionState::kActive);
    EXPECT_TRUE(boundary.Suspend("indexing"));
    EXPECT_EQ(boundary.GetState("indexing"), MemoryExtensionState::kSuspended);
    EXPECT_FALSE(boundary.Activate("missing"));
    EXPECT_EQ(boundary.GetState("missing"), MemoryExtensionState::kDetached);

    ak::KernelMetadata configuration;
    configuration.name = "indexing-config";
    EXPECT_TRUE(boundary.SetConfiguration("indexing", configuration));
    EXPECT_FALSE(boundary.SetConfiguration("missing", configuration));
}

TEST(MemoryExtensionBoundary, ValidatesIntegrityAndCompatibility) {
    MemoryExtensionBoundary boundary;
    boundary.Attach(std::make_shared<test::MemoryExtensionDouble>(
        "ok", MakeVersion(1, 0)));
    EXPECT_TRUE(boundary.ValidateIntegrity());
    EXPECT_TRUE(boundary.ValidateCompatibility());

    MemoryExtensionBoundary broken;
    broken.Attach(std::make_shared<test::MemoryExtensionDouble>(
        "broken", MakeVersion(1, 0), MemoryExtensionDomain::kMemory, false));
    EXPECT_FALSE(broken.ValidateIntegrity());

    MemoryExtensionBoundary incompatible;
    incompatible.Attach(std::make_shared<test::MemoryExtensionDouble>(
        "old", MakeVersion(2, 0)));
    EXPECT_FALSE(incompatible.ValidateCompatibility());
}

TEST(MemoryExtensionBoundary, RejectsForeignExtensions) {
    // Agent/Context/Planner/Tool/Unknown extensions SHALL NOT
    // attach through the Memory extension boundary.
    for (const MemoryExtensionDomain domain :
         {MemoryExtensionDomain::kAgent, MemoryExtensionDomain::kContext,
          MemoryExtensionDomain::kPlanner, MemoryExtensionDomain::kTool,
          MemoryExtensionDomain::kUnknown}) {
        MemoryExtensionBoundary boundary;
        const MemoryAttachResult result = boundary.Attach(
            std::make_shared<test::MemoryExtensionDouble>(
                "foreign", MakeVersion(1, 0), domain));
        EXPECT_FALSE(result.accepted)
            << "domain " << static_cast<int>(domain) << " must be rejected";
        EXPECT_NE(std::string(result.message), "");
        EXPECT_EQ(boundary.Count(), 0);
        EXPECT_FALSE(boundary.ContainsForeignExtension());
    }
}

TEST(MemoryExtensionBoundary, BoundaryValidationReportsConformance) {
    MemoryExtensionBoundary boundary;
    boundary.Attach(std::make_shared<test::MemoryExtensionDouble>(
        "retrieval-augmentation", MakeVersion(1, 0)));

    ak::DiagnosticSink sink;
    boundary.ValidateBoundary(sink);
    EXPECT_EQ(sink.ErrorCount(), 0);
    EXPECT_FALSE(boundary.ContainsForeignExtension());
}

TEST(MemoryExtensionBoundary, MemoryRootOwnsTheExtensionBoundary) {
    Memory memory(MakeMemoryIdentity(1));
    auto extension = std::make_shared<test::MemoryExtensionDouble>(
        "policy", MakeVersion(1, 0));

    const MemoryAttachResult result = memory.Extensions().Attach(extension);
    ASSERT_TRUE(result.accepted);
    EXPECT_EQ(memory.Extensions().Count(), 1);

    const MemoryAttachResult foreign = memory.Extensions().Attach(
        std::make_shared<test::MemoryExtensionDouble>(
            "context-extension", MakeVersion(1, 0),
            MemoryExtensionDomain::kContext));
    EXPECT_FALSE(foreign.accepted);
    EXPECT_EQ(memory.Extensions().Count(), 1);
    EXPECT_FALSE(memory.Extensions().ContainsForeignExtension());
}

}  // namespace
}  // namespace ak::memory