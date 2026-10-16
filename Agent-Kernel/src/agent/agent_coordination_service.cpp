// ============================================================
// Agent Kernel - AgentCoordinationService (Agent boundary)
// ============================================================
// Implementation of the Agent-owned coordination service.
// ============================================================

#include <agent_kernel/agent/coordination/agent_coordination_service.hpp>

#include <string_view>
#include <utility>
#include <vector>

namespace ak::agent {

bool AgentCoordinationService::BindMemory(IMemoryContract& contract) noexcept {
    memory_ = &contract;
    return true;
}

bool AgentCoordinationService::BindContext(IContextContract& contract) noexcept {
    context_ = &contract;
    return true;
}

bool AgentCoordinationService::BindPlanner(IPlannerContract& contract) noexcept {
    planner_ = &contract;
    return true;
}

bool AgentCoordinationService::BindTool(IToolContract& contract) noexcept {
    tool_ = &contract;
    return true;
}

bool AgentCoordinationService::IsBound(SubsystemId id) const noexcept {
    switch (id) {
        case SubsystemId::kMemory:
            return memory_ != nullptr;
        case SubsystemId::kContext:
            return context_ != nullptr;
        case SubsystemId::kPlanner:
            return planner_ != nullptr;
        case SubsystemId::kTool:
            return tool_ != nullptr;
    }
    return false;
}

bool AgentCoordinationService::AllBound() const noexcept {
    return IsBound(SubsystemId::kMemory) &&
           IsBound(SubsystemId::kContext) &&
           IsBound(SubsystemId::kPlanner) &&
           IsBound(SubsystemId::kTool);
}

CoordinationResult AgentCoordinationService::Coordinate(ISubsystemContract* contract) const {
    if (contract == nullptr) {
        return {false, "subsystem contract is not bound"};
    }
    CoordinationAcknowledgement acknowledgement =
        contract->AcknowledgeCoordination();
    if (!acknowledgement.accepted) {
        return {false, acknowledgement.message};
    }
    return {true, acknowledgement.message};
}

CoordinationResult AgentCoordinationService::CoordinateMemory() {
    return Coordinate(memory_);
}

CoordinationResult AgentCoordinationService::CoordinateContext() {
    return Coordinate(context_);
}

CoordinationResult AgentCoordinationService::CoordinatePlanner() {
    return Coordinate(planner_);
}

CoordinationResult AgentCoordinationService::CoordinateTool() {
    return Coordinate(tool_);
}

std::vector<std::string_view> AgentCoordinationService::CoordinatedSubsystems() const {
    std::vector<std::string_view> names;
    if (memory_ != nullptr) {
        names.push_back(memory_->ContractName());
    }
    if (context_ != nullptr) {
        names.push_back(context_->ContractName());
    }
    if (planner_ != nullptr) {
        names.push_back(planner_->ContractName());
    }
    if (tool_ != nullptr) {
        names.push_back(tool_->ContractName());
    }
    return names;
}

std::size_t AgentCoordinationService::CoordinatedSubsystemCount() const noexcept {
    std::size_t count = 0;
    if (memory_ != nullptr) {
        ++count;
    }
    if (context_ != nullptr) {
        ++count;
    }
    if (planner_ != nullptr) {
        ++count;
    }
    if (tool_ != nullptr) {
        ++count;
    }
    return count;
}

}  // namespace ak::agent
