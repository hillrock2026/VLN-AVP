// ============================================================
// planner_extension_test.cpp - P1-IS005 extension boundary
// ============================================================
// PLN-027: Planner owns Planner Extensions; only kPlanner domain
// extensions attach; foreign domains are rejected; no bypass of
// Planner ownership or lifecycle.
// ============================================================

#include <agent_kernel/planner/planner.hpp>
#include <agent_kernel/planner/planner_extensions.hpp>
#include <agent_kernel/planner/planning_engine.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <utility>

#include "test_doubles.hpp"

namespace ak::planner {
namespace {

using test::PlannerTestFixture;

class ExtensionDouble final : public IPlannerExtension {
public:
    ExtensionDouble(std::string name,
                    PlannerExtensionDomain domain,
                    std::uint32_t version =
                        PlannerExtensionBoundary::SupportedMajorVersion(),
                    bool self_check = true)
        : name_(std::move(name)),
          domain_(domain),
          version_(version),
          self_check_(self_check) {}

    ~ExtensionDouble() noexcept override = default;

    std::string_view Name() const noexcept override { return name_; }
    PlannerExtensionDomain Domain() const noexcept override { return domain_; }
    std::uint32_t MajorVersion() const noexcept override { return version_; }
    bool SelfCheck() const noexcept override { return self_check_; }

private:
    std::string name_;
    PlannerExtensionDomain domain_;
    std::uint32_t version_;
    bool self_check_;
};

TEST(PlannerExtension, OnlyPlannerDomainAttaches) {
    PlannerExtensionBoundary boundary;

    auto planner_extension =
        std::make_shared<ExtensionDouble>("planner-1", PlannerExtensionDomain::kPlanner);
    EXPECT_TRUE(boundary.Attach(planner_extension).accepted);
    EXPECT_EQ(boundary.Count(), 1);
    EXPECT_TRUE(boundary.Contains("planner-1"));
    EXPECT_FALSE(boundary.ContainsForeignExtension());

    auto agent_extension =
        std::make_shared<ExtensionDouble>("agent-1", PlannerExtensionDomain::kAgent);
    EXPECT_FALSE(boundary.Attach(agent_extension).accepted);
    auto memory_extension =
        std::make_shared<ExtensionDouble>("memory-1", PlannerExtensionDomain::kMemory);
    EXPECT_FALSE(boundary.Attach(memory_extension).accepted);
    auto context_extension =
        std::make_shared<ExtensionDouble>("context-1", PlannerExtensionDomain::kContext);
    EXPECT_FALSE(boundary.Attach(context_extension).accepted);
    auto tool_extension =
        std::make_shared<ExtensionDouble>("tool-1", PlannerExtensionDomain::kTool);
    EXPECT_FALSE(boundary.Attach(tool_extension).accepted);

    EXPECT_EQ(boundary.Count(), 1);
    EXPECT_FALSE(boundary.ContainsForeignExtension());
}

TEST(PlannerExtension, NullVersionAndSelfCheckAreEnforced) {
    PlannerExtensionBoundary boundary;

    EXPECT_FALSE(boundary.Attach(nullptr).accepted);

    auto wrong_version = std::make_shared<ExtensionDouble>(
        "wrong-version", PlannerExtensionDomain::kPlanner, 2);
    EXPECT_FALSE(boundary.Attach(wrong_version).accepted);

    auto failed_self_check = std::make_shared<ExtensionDouble>(
        "failed-check", PlannerExtensionDomain::kPlanner, 1, false);
    EXPECT_FALSE(boundary.Attach(failed_self_check).accepted);

    EXPECT_EQ(boundary.Count(), 0);
}

TEST(PlannerExtension, DetachAndEnumerate) {
    PlannerExtensionBoundary boundary;
    boundary.Attach(std::make_shared<ExtensionDouble>(
        "alpha", PlannerExtensionDomain::kPlanner));
    boundary.Attach(std::make_shared<ExtensionDouble>(
        "beta", PlannerExtensionDomain::kPlanner));

    const auto names = boundary.Enumerate();
    EXPECT_EQ(names.size(), 2);

    EXPECT_TRUE(boundary.Detach("alpha"));
    EXPECT_FALSE(boundary.Contains("alpha"));
    EXPECT_EQ(boundary.Count(), 1);
    EXPECT_FALSE(boundary.Detach("missing"));
}

TEST(PlannerExtension, IntegrityValidation) {
    PlannerExtensionBoundary boundary;
    boundary.Attach(std::make_shared<ExtensionDouble>(
        "planner-1", PlannerExtensionDomain::kPlanner));
    EXPECT_TRUE(boundary.ValidateIntegrity());
}

TEST(PlannerExtension, RootBoundaryRejectsForeignExtensions) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();

    auto planner_extension =
        std::make_shared<ExtensionDouble>("root-planner", PlannerExtensionDomain::kPlanner);
    EXPECT_TRUE(planner.Extensions().Attach(planner_extension).accepted);
    EXPECT_TRUE(planner.Extensions().ValidateIntegrity());

    auto foreign =
        std::make_shared<ExtensionDouble>("root-memory", PlannerExtensionDomain::kMemory);
    EXPECT_FALSE(planner.Extensions().Attach(foreign).accepted);
    EXPECT_FALSE(planner.Extensions().ContainsForeignExtension());
}

}  // namespace
}  // namespace ak::planner
