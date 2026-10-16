// ============================================================
// boundary_validator_test.cpp - P1-IS002 validation tests
// ============================================================
// AG-010/AG-011: Agent-owned ownership/dependency validation
// produces owner-scoped diagnostics for identity, state,
// coordination, Runtime port, extension, and composition
// conformance.
// ============================================================

#include <agent_kernel/agent/agent.hpp>
#include <agent_kernel/agent/execution/execution_composition.hpp>
#include <agent_kernel/agent/validation/agent_boundary_validator.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <string>

#include "test_doubles.hpp"

namespace ak::agent {
namespace {

class BoundaryValidatorTest : public ::testing::Test {
protected:
    void SetUp() override {
        test::BindAllContracts(agent_, memory_, context_, planner_, tool_);
        ASSERT_TRUE(agent_.Initialize().Accepted());
    }

    Agent agent_{MakeAgentIdentity(1)};
    test::MemoryContractDouble memory_;
    test::ContextContractDouble context_;
    test::PlannerContractDouble planner_;
    test::ToolContractDouble tool_;
};

TEST_F(BoundaryValidatorTest, ValidAgentProducesNoErrors) {
    ak::DiagnosticSink sink;
    AgentBoundaryValidator validator;
    validator.Validate(agent_, sink);
    EXPECT_EQ(sink.ErrorCount(), 0);
}

TEST_F(BoundaryValidatorTest, MissingContractIsReported) {
    Agent incomplete(MakeAgentIdentity(2));
    incomplete.Coordination().BindMemory(memory_);
    incomplete.Coordination().BindContext(context_);
    incomplete.Coordination().BindPlanner(planner_);
    // Tool deliberately not bound.

    ak::DiagnosticSink sink;
    AgentBoundaryValidator validator;
    validator.Validate(incomplete, sink);
    EXPECT_GE(sink.ErrorCount(), 1);
}

TEST_F(BoundaryValidatorTest, InvalidIdentityIsReported) {
    Agent invalid(MakeAgentIdentity(0));
    test::MemoryContractDouble memory;
    test::ContextContractDouble context;
    test::PlannerContractDouble planner;
    test::ToolContractDouble tool;
    test::BindAllContracts(invalid, memory, context, planner, tool);

    ak::DiagnosticSink sink;
    AgentBoundaryValidator validator;
    validator.Validate(invalid, sink);
    EXPECT_GE(sink.ErrorCount(), 1);
}

TEST_F(BoundaryValidatorTest, InvalidCompositionIsReported) {
    Agent agent(MakeAgentIdentity(1));
    test::MemoryContractDouble memory;
    test::ContextContractDouble context;
    test::PlannerContractDouble planner;
    test::ToolContractDouble tool;
    test::BindAllContracts(agent, memory, context, planner, tool);

    // Cyclic composition representation.
    const std::uint64_t a = agent.Composition().AddStep(
        CompositionStep{0, CompositionStepKind::kTaskComposition, "a", {}, {}, {}});
    const std::uint64_t b = agent.Composition().AddStep(
        CompositionStep{0, CompositionStepKind::kTaskComposition, "b", {}, {}, {}});
    ASSERT_TRUE(agent.Composition().AddDependency(a, b));
    ASSERT_TRUE(agent.Composition().AddDependency(b, a));

    ak::DiagnosticSink sink;
    AgentBoundaryValidator validator;
    validator.Validate(agent, sink);
    EXPECT_GE(sink.ErrorCount(), 1);
}

TEST_F(BoundaryValidatorTest, Phase1StaticPropertyHolds) {
    EXPECT_TRUE(AgentBoundaryValidator::Phase1HasNoConcreteRuntimeDependency());
}

}  // namespace
}  // namespace ak::agent
