// ============================================================
// test_doubles.hpp - P1-IS002 Agent test doubles
// ============================================================
// Phase 1 test doubles for the peer subsystem contracts and
// Agent-specific extensions. The doubles record Agent
// coordination calls and carry no cross-subsystem references:
// they cannot coordinate one another and cannot reach the
// Agent. Subsystem behavior remains subsystem-owned; these
// doubles only acknowledge the coordination boundary.
//
// This file intentionally includes NO Runtime header.
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <string_view>

#include <agent_kernel/agent/agent.hpp>
#include <agent_kernel/agent/coordination/agent_coordination_service.hpp>
#include <agent_kernel/agent/coordination/i_context_contract.hpp>
#include <agent_kernel/agent/coordination/i_memory_contract.hpp>
#include <agent_kernel/agent/coordination/i_planner_contract.hpp>
#include <agent_kernel/agent/coordination/i_tool_contract.hpp>
#include <agent_kernel/agent/extension/agent_extension_boundary.hpp>

namespace ak::agent {
namespace test {

// ------------------------------------------------------------
// Peer subsystem contract doubles
// ------------------------------------------------------------
// Each double records how many times the Agent coordinated it.
// A double holds no Agent reference and no reference to any
// other subsystem: no hidden coordination path exists.

class MemoryContractDouble : public IMemoryContract {
public:
    ~MemoryContractDouble() noexcept override = default;

    std::string_view ContractName() const noexcept override {
        return "Memory";
    }

    CoordinationAcknowledgement AcknowledgeCoordination() override {
        ++acknowledged_count;
        return {true, "memory coordination acknowledged"};
    }

    std::size_t acknowledged_count = 0;
};

class ContextContractDouble : public IContextContract {
public:
    ~ContextContractDouble() noexcept override = default;

    std::string_view ContractName() const noexcept override {
        return "Context";
    }

    CoordinationAcknowledgement AcknowledgeCoordination() override {
        ++acknowledged_count;
        return {true, "context coordination acknowledged"};
    }

    std::size_t acknowledged_count = 0;
};

class PlannerContractDouble : public IPlannerContract {
public:
    ~PlannerContractDouble() noexcept override = default;

    std::string_view ContractName() const noexcept override {
        return "Planner";
    }

    CoordinationAcknowledgement AcknowledgeCoordination() override {
        ++acknowledged_count;
        return {true, "planner coordination acknowledged"};
    }

    std::size_t acknowledged_count = 0;
};

class ToolContractDouble : public IToolContract {
public:
    ~ToolContractDouble() noexcept override = default;

    std::string_view ContractName() const noexcept override {
        return "Tool";
    }

    CoordinationAcknowledgement AcknowledgeCoordination() override {
        ++acknowledged_count;
        return {true, "tool coordination acknowledged"};
    }

    std::size_t acknowledged_count = 0;
};

// ------------------------------------------------------------
// Agent-specific extension doubles
// ------------------------------------------------------------

class AgentExtensionDouble : public IAgentExtension {
public:
    AgentExtensionDouble(std::string name, AgentExtensionVersion version,
                         AgentExtensionDomain domain =
                             AgentExtensionDomain::kAgentSpecific,
                         bool self_check = true)
        : name_(std::move(name)),
          version_(version),
          domain_(domain),
          self_check_(self_check) {}

    ~AgentExtensionDouble() noexcept override = default;

    std::string_view Name() const noexcept override { return name_; }
    AgentExtensionDomain Domain() const noexcept override { return domain_; }
    AgentExtensionVersion Version() const noexcept override { return version_; }
    bool SelfCheck() const noexcept override { return self_check_; }

private:
    std::string name_;
    AgentExtensionVersion version_;
    AgentExtensionDomain domain_;
    bool self_check_;
};

// Binds the four peer subsystem contracts to an Agent.
inline void BindAllContracts(Agent& agent, MemoryContractDouble& memory,
                             ContextContractDouble& context,
                             PlannerContractDouble& planner,
                             ToolContractDouble& tool) {
    agent.Coordination().BindMemory(memory);
    agent.Coordination().BindContext(context);
    agent.Coordination().BindPlanner(planner);
    agent.Coordination().BindTool(tool);
}

}  // namespace test
}  // namespace ak::agent
