// ============================================================
// coordination_test.cpp - P1-IS002 coordination conformance
// ============================================================
// AG-003..AG-006, AG-020: Agent is the sole cross-subsystem
// coordinator; it coordinates Memory, Context, Planner, and
// Tool through their architectural contracts; subsystem
// ownership is not absorbed; no hidden coordination path
// exists.
// ============================================================

#include <agent_kernel/agent/agent.hpp>
#include <agent_kernel/agent/coordination/agent_coordination_service.hpp>
#include <agent_kernel/agent/coordination/subsystem_contract.hpp>

#include <gtest/gtest.h>

#include <string>
#include <string_view>
#include <type_traits>
#include <vector>

#include "test_doubles.hpp"

namespace ak::agent {
namespace {

// The coordination service must expose no operation that lets
// one subsystem contract coordinate another (no hidden
// coordination path).
template <typename T, typename = void>
struct HasCrossSubsystemCoordinate : std::false_type {};
template <typename T>
struct HasCrossSubsystemCoordinate<
    T, std::void_t<decltype(std::declval<T&>().CoordinateFromSubsystem(
           SubsystemId::kMemory))>> : std::true_type {};

// The Agent must expose no ownership-transfer API over the
// subsystem contracts (Agent does not absorb subsystem
// ownership).
template <typename T, typename = void>
struct HasTakeContractOwnership : std::false_type {};
template <typename T>
struct HasTakeContractOwnership<
    T, std::void_t<decltype(std::declval<T&>().TakeContractOwnership(
           SubsystemId::kMemory))>> : std::true_type {};

TEST(Coordination, BindsAllFourPeerContracts) {
    Agent agent(MakeAgentIdentity(1));
    test::MemoryContractDouble memory;
    test::ContextContractDouble context;
    test::PlannerContractDouble planner;
    test::ToolContractDouble tool;

    EXPECT_FALSE(agent.HasAllSubsystemContracts());

    agent.Coordination().BindMemory(memory);
    agent.Coordination().BindContext(context);
    agent.Coordination().BindPlanner(planner);
    agent.Coordination().BindTool(tool);

    EXPECT_TRUE(agent.HasAllSubsystemContracts());
    EXPECT_TRUE(agent.Coordination().AllBound());
    EXPECT_EQ(agent.Coordination().CoordinatedSubsystemCount(), 4);
}

TEST(Coordination, ListsCanonicalPeerOrder) {
    AgentCoordinationService service;
    test::MemoryContractDouble memory;
    test::ContextContractDouble context;
    test::PlannerContractDouble planner;
    test::ToolContractDouble tool;

    service.BindMemory(memory);
    service.BindTool(tool);
    service.BindPlanner(planner);
    service.BindContext(context);

    const std::vector<std::string_view> names =
        service.CoordinatedSubsystems();
    ASSERT_EQ(names.size(), 4);
    EXPECT_EQ(std::string(names[0]), "Memory");
    EXPECT_EQ(std::string(names[1]), "Context");
    EXPECT_EQ(std::string(names[2]), "Planner");
    EXPECT_EQ(std::string(names[3]), "Tool");
}

TEST(Coordination, AgentCoordinationReachesEachContract) {
    Agent agent(MakeAgentIdentity(1));
    test::MemoryContractDouble memory;
    test::ContextContractDouble context;
    test::PlannerContractDouble planner;
    test::ToolContractDouble tool;
    test::BindAllContracts(agent, memory, context, planner, tool);

    const CoordinationResult memory_result = agent.Coordination().CoordinateMemory();
    const CoordinationResult context_result = agent.Coordination().CoordinateContext();
    const CoordinationResult planner_result = agent.Coordination().CoordinatePlanner();
    const CoordinationResult tool_result = agent.Coordination().CoordinateTool();

    EXPECT_TRUE(memory_result.accepted);
    EXPECT_TRUE(context_result.accepted);
    EXPECT_TRUE(planner_result.accepted);
    EXPECT_TRUE(tool_result.accepted);

    EXPECT_EQ(memory.acknowledged_count, 1);
    EXPECT_EQ(context.acknowledged_count, 1);
    EXPECT_EQ(planner.acknowledged_count, 1);
    EXPECT_EQ(tool.acknowledged_count, 1);
}

TEST(Coordination, UnboundContractCoordinationIsRejected) {
    AgentCoordinationService service;
    test::MemoryContractDouble memory;
    service.BindMemory(memory);

    const CoordinationResult context_result = service.CoordinateContext();
    EXPECT_FALSE(context_result.accepted);
    EXPECT_NE(std::string(context_result.message), "");

    EXPECT_TRUE(service.CoordinateMemory().accepted);
}

TEST(Coordination, AgentIsSoleCrossSubsystemCoordinator) {
    // No operation allows a subsystem contract to coordinate
    // another subsystem.
    static_assert(!HasCrossSubsystemCoordinate<AgentCoordinationService>::value,
                  "coordination service must not expose cross-subsystem coordination "
                  "from a subsystem");
    // The Agent does not absorb contract ownership.
    static_assert(!HasTakeContractOwnership<Agent>::value,
                  "Agent must not take ownership of subsystem contracts");
}

TEST(Coordination, AgentHoldsNonOwningReferences) {
    Agent agent(MakeAgentIdentity(1));
    test::MemoryContractDouble memory;
    test::ContextContractDouble context;
    test::PlannerContractDouble planner;
    test::ToolContractDouble tool;
    test::BindAllContracts(agent, memory, context, planner, tool);

    // Destroy the Agent: the subsystem doubles remain valid and
    // usable. The Agent held non-owning references only.
    {
        Agent local_agent(MakeAgentIdentity(2));
        test::BindAllContracts(local_agent, memory, context, planner, tool);
        ASSERT_TRUE(local_agent.Initialize().Accepted());
        ASSERT_TRUE(local_agent.BeginCoordination().Accepted());
    }

    EXPECT_TRUE(memory.ContractName() == "Memory");
    EXPECT_TRUE(memory.AcknowledgeCoordination().accepted);
    EXPECT_EQ(memory.acknowledged_count, 2);
}

}  // namespace
}  // namespace ak::agent
