// ============================================================
// Agent Kernel - AgentCoordinationService (Agent boundary)
// ============================================================
// Agent-owned coordination service.
//
// P1-IS002 scope (Chapter 9.4 - Coordination Service):
// - An Agent-owned coordination service MAY be used; it SHALL
//   remain Agent-owned, coordinate Agent responsibilities,
//   preserve subsystem ownership, preserve lifecycle
//   independence, and preserve Runtime isolation.
// - It is the sole cross-subsystem coordination path held by
//   the Agent; it never becomes a new architectural subsystem.
//
// NON-responsibilities:
// - The service holds NON-OWNING references to subsystem
//   contracts; it does not own or destroy subsystem objects.
// - It does not implement Memory/Context/Planner/Tool
//   behavior and is not a universal coordinator.
// ============================================================

#pragma once

#include <cstdint>
#include <string_view>
#include <vector>

#include <agent_kernel/agent/coordination/i_context_contract.hpp>
#include <agent_kernel/agent/coordination/i_memory_contract.hpp>
#include <agent_kernel/agent/coordination/i_planner_contract.hpp>
#include <agent_kernel/agent/coordination/i_tool_contract.hpp>
#include <agent_kernel/agent/coordination/subsystem_contract.hpp>

namespace ak::agent {

// Result of an Agent coordination action.
struct CoordinationResult {
    bool accepted = false;
    const char* message = "";
};

class AgentCoordinationService {
public:
    AgentCoordinationService() = default;

    // Binds a peer subsystem contract (non-owning reference).
    bool BindMemory(IMemoryContract& contract) noexcept;
    bool BindContext(IContextContract& contract) noexcept;
    bool BindPlanner(IPlannerContract& contract) noexcept;
    bool BindTool(IToolContract& contract) noexcept;

    [[nodiscard]] bool IsBound(SubsystemId id) const noexcept;
    [[nodiscard]] bool AllBound() const noexcept;

    // Phase 1 coordination acknowledgments invoked by the
    // Agent when it coordinates the peer subsystem.
    [[nodiscard]] CoordinationResult CoordinateMemory();
    [[nodiscard]] CoordinationResult CoordinateContext();
    [[nodiscard]] CoordinationResult CoordinatePlanner();
    [[nodiscard]] CoordinationResult CoordinateTool();

    // Names of currently bound subsystem contracts, in the
    // canonical peer order (Memory, Context, Planner, Tool).
    [[nodiscard]] std::vector<std::string_view> CoordinatedSubsystems() const;

    [[nodiscard]] std::size_t CoordinatedSubsystemCount() const noexcept;

private:
    [[nodiscard]] CoordinationResult Coordinate(ISubsystemContract* contract) const;

    IMemoryContract* memory_ = nullptr;
    IContextContract* context_ = nullptr;
    IPlannerContract* planner_ = nullptr;
    IToolContract* tool_ = nullptr;
};

}  // namespace ak::agent
