// ============================================================
// extension_boundary_test.cpp - P1-IS002 extension conformance
// ============================================================
// AG-019: Agent owns the Agent-specific extension boundary and
// directly coordinates Agent-specific extensions. Planner,
// Memory, Context, and Tool extensions remain subsystem-owned
// and cannot attach through the Agent-specific boundary.
// ============================================================

#include <agent_kernel/agent/agent.hpp>
#include <agent_kernel/agent/extension/agent_extension_boundary.hpp>

#include <gtest/gtest.h>

#include <memory>
#include <string>
#include <vector>

#include "test_doubles.hpp"

namespace ak::agent {
namespace {

AgentExtensionVersion MakeVersion(std::uint32_t major,
                                  std::uint32_t minor = 0) {
    return AgentExtensionVersion{major, minor};
}

TEST(AgentExtensionBoundary, AttachesAgentSpecificExtensions) {
    AgentExtensionBoundary boundary;
    auto extension = std::make_shared<test::AgentExtensionDouble>(
        "reasoning", MakeVersion(1, 2));

    const AttachResult result = boundary.Attach(extension);
    EXPECT_TRUE(result.accepted);
    EXPECT_EQ(boundary.Count(), 1);
    EXPECT_TRUE(boundary.Contains("reasoning"));

    const std::vector<std::string> names = boundary.Enumerate();
    ASSERT_EQ(names.size(), 1);
    EXPECT_EQ(names[0], "reasoning");
}

TEST(AgentExtensionBoundary, RejectsDuplicateNames) {
    AgentExtensionBoundary boundary;
    boundary.Attach(std::make_shared<test::AgentExtensionDouble>(
        "policy", MakeVersion(1, 0)));
    const AttachResult duplicate = boundary.Attach(
        std::make_shared<test::AgentExtensionDouble>("policy", MakeVersion(1, 0)));
    EXPECT_FALSE(duplicate.accepted);
    EXPECT_EQ(boundary.Count(), 1);
}

TEST(AgentExtensionBoundary, ManagesExtensionLifecycle) {
    AgentExtensionBoundary boundary;
    boundary.Attach(std::make_shared<test::AgentExtensionDouble>(
        "perception", MakeVersion(1, 0)));

    EXPECT_EQ(boundary.GetState("perception"), AgentExtensionState::kAttached);
    EXPECT_TRUE(boundary.Activate("perception"));
    EXPECT_EQ(boundary.GetState("perception"), AgentExtensionState::kActive);
    EXPECT_TRUE(boundary.Suspend("perception"));
    EXPECT_EQ(boundary.GetState("perception"), AgentExtensionState::kSuspended);

    // Unknown extension: lifecycle operations fail cleanly.
    EXPECT_FALSE(boundary.Activate("missing"));
    EXPECT_EQ(boundary.GetState("missing"), AgentExtensionState::kDetached);
}

TEST(AgentExtensionBoundary, ManagesConfiguration) {
    AgentExtensionBoundary boundary;
    boundary.Attach(std::make_shared<test::AgentExtensionDouble>(
        "learning", MakeVersion(1, 0)));

    ak::KernelMetadata configuration;
    configuration.name = "learning-config";
    EXPECT_TRUE(boundary.SetConfiguration("learning", configuration));
    EXPECT_FALSE(boundary.SetConfiguration("missing", configuration));
}

TEST(AgentExtensionBoundary, ValidatesIntegrityAndCompatibility) {
    AgentExtensionBoundary boundary;
    boundary.Attach(std::make_shared<test::AgentExtensionDouble>(
        "ok", MakeVersion(1, 0), AgentExtensionDomain::kAgentSpecific, true));
    EXPECT_TRUE(boundary.ValidateIntegrity());
    EXPECT_TRUE(boundary.ValidateCompatibility());

    AgentExtensionBoundary broken;
    broken.Attach(std::make_shared<test::AgentExtensionDouble>(
        "broken", MakeVersion(1, 0), AgentExtensionDomain::kAgentSpecific, false));
    EXPECT_FALSE(broken.ValidateIntegrity());

    AgentExtensionBoundary incompatible;
    incompatible.Attach(std::make_shared<test::AgentExtensionDouble>(
        "old", MakeVersion(2, 0)));
    EXPECT_FALSE(incompatible.ValidateCompatibility());
}

TEST(AgentExtensionBoundary, RejectsSubsystemExtensions) {
    // Planner/Memory/Context/Tool extensions SHALL NOT attach
    // through the Agent-specific extension boundary.
    for (const AgentExtensionDomain domain :
         {AgentExtensionDomain::kPlanner, AgentExtensionDomain::kMemory,
          AgentExtensionDomain::kContext, AgentExtensionDomain::kTool,
          AgentExtensionDomain::kUnknown}) {
        AgentExtensionBoundary boundary;
        const AttachResult result = boundary.Attach(
            std::make_shared<test::AgentExtensionDouble>(
                "subsystem-extension", MakeVersion(1, 0), domain));
        EXPECT_FALSE(result.accepted)
            << "domain " << static_cast<int>(domain) << " must be rejected";
        EXPECT_NE(std::string(result.message), "");
        EXPECT_EQ(boundary.Count(), 0);
        EXPECT_FALSE(boundary.ContainsSubsystemExtension());
    }
}

TEST(AgentExtensionBoundary, BoundaryValidationReportsConformance) {
    AgentExtensionBoundary boundary;
    boundary.Attach(std::make_shared<test::AgentExtensionDouble>(
        "reasoning", MakeVersion(1, 0)));

    ak::DiagnosticSink sink;
    boundary.ValidateBoundary(sink);
    EXPECT_EQ(sink.ErrorCount(), 0);
    EXPECT_FALSE(boundary.ContainsSubsystemExtension());
}

TEST(AgentExtensionBoundary, DetachRemovesExtension) {
    AgentExtensionBoundary boundary;
    boundary.Attach(std::make_shared<test::AgentExtensionDouble>(
        "reasoning", MakeVersion(1, 0)));
    EXPECT_TRUE(boundary.Detach("reasoning"));
    EXPECT_EQ(boundary.Count(), 0);
    EXPECT_FALSE(boundary.Detach("reasoning"));
}

TEST(AgentExtensionBoundary, AgentOwnsAndCoordinatesItsExtensions) {
    Agent agent(MakeAgentIdentity(1));
    auto extension = std::make_shared<test::AgentExtensionDouble>(
        "policy", MakeVersion(1, 0));

    const AttachResult result = agent.Extensions().Attach(extension);
    ASSERT_TRUE(result.accepted);
    EXPECT_EQ(agent.Extensions().Count(), 1);
    EXPECT_TRUE(agent.Extensions().Contains("policy"));

    // Subsystem extensions are rejected on the Agent boundary.
    const AttachResult rejected = agent.Extensions().Attach(
        std::make_shared<test::AgentExtensionDouble>(
            "planner-planning-strategy", MakeVersion(1, 0),
            AgentExtensionDomain::kPlanner));
    EXPECT_FALSE(rejected.accepted);
    EXPECT_EQ(agent.Extensions().Count(), 1);
    EXPECT_FALSE(agent.Extensions().ContainsSubsystemExtension());
}

}  // namespace
}  // namespace ak::agent
