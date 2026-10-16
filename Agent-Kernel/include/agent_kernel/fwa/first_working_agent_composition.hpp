// ============================================================
// Agent Kernel - FirstWorkingAgentComposition (Agent boundary)
// ============================================================
// First Working Agent Sprint 閳?TASK 6 Rev2 鎼?3, 鎼?2-鎼?4.
//
// Agent-owned composition root (NOT a second Agent, NOT a
// subsystem, NOT a Runtime). It owns the existing Agent, the
// three Agent-owned hosts/bindings, the existing ak::tool::Tool
// root + AgentToolBinding (governance decision 鎼?A), Context,
// Memory, the four acknowledge adapters, the ModelBoundary, the
// ToolExecutionBoundary, and the sequential loop driver.
//
// Ownership / boundary rules (INV-001..INV-025):
// - Agent coordinates Tool exclusively through AgentToolBinding
//   (INV-004). No Tool()/GetTool()/Providers() accessor exists
//   (INV-025; TOL-084 preserved).
// - Tool execution is NOT implemented here (INV-014): only
//   capability discovery + invocation preparation; the test-
//   scoped ToolExecutionBoundary stands in for Runtime execution.
// - No Runtime type is referenced and no Runtime target is linked
//   (INV-021).
//
// Entry methods (OBS-04 naming): Initialize(), StepCycle(), Run().
// ============================================================

#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>

#include <agent_kernel/agent/agent.hpp>
#include <agent_kernel/agent/agent_state.hpp>
#include <agent_kernel/fwa/first_working_agent_configuration.hpp>
#include <agent_kernel/agent/coordination/i_context_contract.hpp>
#include <agent_kernel/agent/coordination/i_memory_contract.hpp>
#include <agent_kernel/agent/coordination/i_planner_contract.hpp>
#include <agent_kernel/agent/coordination/i_tool_contract.hpp>
#include <agent_kernel/agent/execution/execution_objective.hpp>
#include <agent_kernel/agent_planner/agent_planner_host.hpp>
#include <agent_kernel/agent_prompt/agent_prompt_host.hpp>
#include <agent_kernel/agent_tool/agent_tool_binding.hpp>
#include <agent_kernel/context/context.hpp>
#include <agent_kernel/memory/memory.hpp>
#include <agent_kernel/tool/tool.hpp>

namespace ak::agent {

// Composition-level test-observable outcome of one cycle / run
// (TASK 6 Rev2 鎼?2). Value carrier only; no lifecycle state.
struct CycleOutcome {
    bool completed = false;
    std::string summary;                                  // deterministic summary
    ak::agent::AgentState final_state = ak::agent::AgentState::kUninitialized;
    std::string diagnostics;                              // observable evidence
};

// The First Working Agent integration composition root.
class FirstWorkingAgentComposition {
public:
    explicit FirstWorkingAgentComposition(
        FirstWorkingAgentConfiguration configuration);

    FirstWorkingAgentComposition(const FirstWorkingAgentComposition&) = delete;
    FirstWorkingAgentComposition& operator=(const FirstWorkingAgentComposition&) =
        delete;

    // Full initialization sequence (TASK 6 Rev2 鎼?3): Tool
    // provider registration, four acknowledge adapters, Agent
    // lifecycle + objective acceptance + BeginCoordination,
    // Context initialization, Memory participation, Planner
    // lifecycle.
    [[nodiscard]] bool Initialize(const ExecutionObjective& objective);

    // One full planning -> prompt -> model -> action cycle.
    [[nodiscard]] CycleOutcome StepCycle();

    // Drives StepCycle() up to max_cycles until kComplete,
    // kInvalid, or a deterministic failure terminates the cycle.
    [[nodiscard]] CycleOutcome Run();

    // -- Observability (existing surfaces reused) --
    [[nodiscard]] ak::agent::Agent& Agent() noexcept { return agent_; }
    [[nodiscard]] const ak::agent::Agent& Agent() const noexcept { return agent_; }
    [[nodiscard]] ak::context::Context& Context() noexcept { return context_; }
    [[nodiscard]] const ak::context::Context& Context() const noexcept {
        return context_;
    }
    [[nodiscard]] ak::memory::Memory& Memory() noexcept { return memory_; }
    [[nodiscard]] const ak::memory::Memory& Memory() const noexcept {
        return memory_;
    }
    [[nodiscard]] bool Initialized() const noexcept { return initialized_; }

private:
    // --------------------------------------------------------
    // Four acknowledge adapters (TASK 6 Rev2 鎼?4) 閳?satisfy
    // Agent::BeginCoordination(); acknowledge coordination only.
    // --------------------------------------------------------
    class MemoryAcknowledgeAdapter final : public IMemoryContract {
    public:
        std::string_view ContractName() const noexcept override { return "Memory"; }
        CoordinationAcknowledgement AcknowledgeCoordination() override {
            return {true, "memory coordination acknowledged"};
        }
    };
    class ContextAcknowledgeAdapter final : public IContextContract {
    public:
        std::string_view ContractName() const noexcept override { return "Context"; }
        CoordinationAcknowledgement AcknowledgeCoordination() override {
            return {true, "context coordination acknowledged"};
        }
    };
    class PlannerAcknowledgeAdapter final : public IPlannerContract {
    public:
        std::string_view ContractName() const noexcept override { return "Planner"; }
        CoordinationAcknowledgement AcknowledgeCoordination() override {
            return {true, "planner coordination acknowledged"};
        }
    };
    class ToolAcknowledgeAdapter final : public IToolContract {
    public:
        std::string_view ContractName() const noexcept override { return "Tool"; }
        CoordinationAcknowledgement AcknowledgeCoordination() override {
            return {true, "tool coordination acknowledged"};
        }
    };

    // Internal cycle termination classification (composition
    // implementation detail; public observation is CycleOutcome).
    enum class CycleTermination {
        kContinue,
        kCompleted,
        kInvalid,
        kFailure
    };
    struct InternalCycleResult {
        CycleTermination termination = CycleTermination::kContinue;
        CycleOutcome outcome;
    };

    [[nodiscard]] InternalCycleResult StepCycleInternal();
    [[nodiscard]] InternalCycleResult ExecuteToolPath(
        const ModelAction& action);
    [[nodiscard]] InternalCycleResult CompleteCycle(
        const std::string& evidence_summary);
    [[nodiscard]] InternalCycleResult FailCycle(
        const std::string& summary, const std::string& diagnostics);
    [[nodiscard]] std::vector<ak::prompt::PromptInputBinding> BuildPromptBindings(
        const std::string& context_content,
        const std::string& memory_content,
        const std::string& plan_payload,
        const std::string& tool_summary) const;
    [[nodiscard]] std::string BuildToolSummary() const;

    // Member order is normative (declaration order = init order):
    // roots before their bindings/views.
    FirstWorkingAgentConfiguration configuration_;
    ak::agent::Agent agent_;
    ak::agent::AgentPlannerHost planner_host_;
    ak::agent::AgentPromptHost prompt_host_;
    ak::tool::Tool tool_;
    ak::agent::AgentToolBinding tool_binding_;
    ak::context::Context context_;
    ak::memory::Memory memory_;
    MemoryAcknowledgeAdapter memory_adapter_;
    ContextAcknowledgeAdapter context_adapter_;
    PlannerAcknowledgeAdapter planner_adapter_;
    ToolAcknowledgeAdapter tool_adapter_;

    // Injection seams + deterministic loop bound.
    ModelBoundary model_boundary_;
    ToolExecutionBoundary tool_execution_boundary_;
    std::size_t max_cycles_ = 8;

    // Loop / cycle state (Agent-owned composition state).
    ObjectiveId objective_id_;
    std::string objective_description_;
    ak::context::ContextObjectId context_object_id_;
    ak::memory::MemoryEntryId memory_entry_id_;
    std::uint64_t planning_request_counter_ = 0;
    std::uint64_t invocation_counter_ = 0;
    bool initialized_ = false;
};

}  // namespace ak::agent
