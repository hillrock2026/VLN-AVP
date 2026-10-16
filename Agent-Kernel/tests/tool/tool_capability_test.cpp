// ============================================================
// tool_capability_test.cpp - P1-IS006 Rev2 Chapter 33.4
// ============================================================
// Capability tests: capability identity (TOL-033), immutable
// published capability (TOL-034), capability contract,
// metadata, availability, and Provider association.
// ============================================================

#include <agent_kernel/tool/tool.hpp>

#include <gtest/gtest.h>

#include <string>

#include "test_doubles.hpp"

namespace ak::tool {
namespace {

TEST(ToolCapability, TOL_033_CapabilityIdentityIsUniqueWithinTool) {
    Tool tool(ToolId("cap-tool-1"),
              ToolConfiguration{"cap", "1.0", "capability test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    const auto first = tool.Capabilities().RegisterCapability(
        test::MakeCapability("cap-a", "provider-a"));
    ASSERT_EQ(first.status, ToolResultStatus::kSuccess);

    const auto duplicate = tool.Capabilities().RegisterCapability(
        test::MakeCapability("cap-a", "provider-b"));
    EXPECT_EQ(duplicate.status, ToolResultStatus::kAlreadyExists);
    EXPECT_FALSE(duplicate.capability.has_value());

    const auto second = tool.Capabilities().RegisterCapability(
        test::MakeCapability("cap-b", "provider-a"));
    EXPECT_EQ(second.status, ToolResultStatus::kSuccess);
}

TEST(ToolCapability, TOL_034_PublishedCapabilityIsImmutable) {
    Tool tool(ToolId("cap-tool-2"),
              ToolConfiguration{"cap", "1.0", "capability test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    ToolCapability original = test::MakeCapability("cap-a", "provider-a");
    ASSERT_EQ(tool.Capabilities().RegisterCapability(original).status,
              ToolResultStatus::kSuccess);

    const auto fetched = tool.Capabilities().Get(CapabilityId("cap-a"));
    ASSERT_EQ(fetched.status, ToolResultStatus::kSuccess);
    ASSERT_TRUE(fetched.capability.has_value());
    EXPECT_EQ(fetched.capability->id, original.id);
    EXPECT_EQ(fetched.capability->description, original.description);

    // Mutating the consumer copy does not mutate the published
    // value (TOL-034).
    ToolCapability mutated = *fetched.capability;
    mutated.description = "mutated-by-consumer";
    mutated.availability = CapabilityAvailability::kUnavailable;
    const auto refetched = tool.Capabilities().Get(CapabilityId("cap-a"));
    ASSERT_EQ(refetched.status, ToolResultStatus::kSuccess);
    EXPECT_EQ(refetched.capability->description, original.description);
    EXPECT_EQ(refetched.capability->availability, original.availability);
}

TEST(ToolCapability, CapabilityContractExposesToolOwnedFields) {
    Tool tool(ToolId("cap-tool-3"),
              ToolConfiguration{"cap", "1.0", "capability test"});
    ASSERT_TRUE(tool.Register().Succeeded());

    ToolCapability capability = test::MakeCapability("cap-a", "provider-a");
    capability.description = "rich description";
    capability.category = "sensing";
    capability.metadata.tags.push_back("extra");
    capability.version = "2.1";
    ASSERT_EQ(tool.Capabilities().RegisterCapability(capability).status,
              ToolResultStatus::kSuccess);

    const auto contract = tool.Capabilities().GetContract(CapabilityId("cap-a"));
    ASSERT_EQ(contract.status, ToolResultStatus::kSuccess);
    ASSERT_TRUE(contract.contract.has_value());
    EXPECT_EQ(contract.contract->capability_id, capability.id);
    EXPECT_EQ(contract.contract->input.schema, capability.input.schema);
    EXPECT_EQ(contract.contract->input.format, "json");
    EXPECT_EQ(contract.contract->output.schema, capability.output.schema);
    EXPECT_EQ(contract.contract->output.format, "json");
    EXPECT_EQ(contract.contract->constraints.constrained,
              capability.constraints.constrained);
    EXPECT_EQ(contract.contract->metadata.name, capability.metadata.name);
    EXPECT_EQ(contract.contract->availability, capability.availability);
    EXPECT_EQ(contract.contract->provider, capability.provider);
    // Tool-owned derivations (documented in the implementation
    // report): compatibility mirrors version; the permission
    // contract mirrors Tool-owned constraints/category.
    EXPECT_EQ(contract.contract->compatibility, "2.1");
    EXPECT_EQ(contract.contract->permissions.policy_scope, "sensing");
    EXPECT_EQ(contract.contract->permissions.required_permissions,
              capability.constraints.constraints);
}

TEST(ToolCapability, CapabilityMetadataAndAvailabilityRoundTrip) {
    Tool tool(ToolId("cap-tool-4"),
              ToolConfiguration{"cap", "1.0", "capability test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    ASSERT_EQ(tool.Capabilities().RegisterCapability(
                  test::MakeCapability("cap-a", "provider-a",
                                       CapabilityAvailability::kConstrained))
                  .status,
              ToolResultStatus::kSuccess);

    const auto availability =
        tool.Availability().GetAvailability(CapabilityId("cap-a"));
    ASSERT_EQ(availability.status, ToolResultStatus::kSuccess);
    EXPECT_EQ(availability.availability, CapabilityAvailability::kConstrained);

    const auto fetched = tool.Capabilities().Get(CapabilityId("cap-a"));
    ASSERT_EQ(fetched.status, ToolResultStatus::kSuccess);
    EXPECT_EQ(fetched.capability->metadata.name, "cap-cap-a");
    EXPECT_EQ(fetched.capability->provider, ProviderId("provider-a"));
    EXPECT_EQ(fetched.capability->availability,
              CapabilityAvailability::kConstrained);
}

}  // namespace
}  // namespace ak::tool