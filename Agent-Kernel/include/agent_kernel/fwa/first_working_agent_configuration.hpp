// ============================================================
// Agent Kernel - FirstWorkingAgentConfiguration (Agent boundary)
// ============================================================
// First Working Agent Sprint — TASK 6 Rev2 §12-§13, §20.
//
// Composition-owned value struct carrying the construction /
// injection values for the First Working Agent composition root.
// It includes the deterministic Tool provider(s) injected at
// construction (governance decision §9A) and the two injection
// seams: ModelBoundary and ToolExecutionBoundary.
//
// NON-responsibilities:
// - No Runtime type, no Model subsystem, no Tool accessor.
// - The deterministic test doubles live ONLY in tests/ (OBS-03;
//   TASK 6.2 Review OBS-002); nothing here is a provider
//   implementation.
// ============================================================

#pragma once

#include <cstddef>
#include <functional>
#include <memory>
#include <string>
#include <vector>

#include <agent_kernel/agent/agent_identity.hpp>
#include <agent_kernel/fwa/model_action.hpp>
#include <agent_kernel/context/context_identity.hpp>
#include <agent_kernel/memory/memory_identity.hpp>
#include <agent_kernel/planner/planner.hpp>
#include <agent_kernel/prompt/prompt_definition.hpp>
#include <agent_kernel/prompt/prompt_result.hpp>
#include <agent_kernel/tool/i_tool_provider.hpp>
#include <agent_kernel/tool/tool.hpp>
#include <agent_kernel/tool/tool_identity.hpp>

namespace ak::agent {

// Minimum deterministic Model boundary (TASK 6 Rev2 §12): a plain
// synchronous callable; not an interface class, not a registry.
using ModelBoundary =
    std::function<ModelAction(const ak::prompt::PromptResult&)>;

// Test-scoped Tool execution seam (TASK 6 Rev2 §20): injected
// callable; concrete deterministic executor lives only in
// tests/first_working_agent/. An unconfigured or empty-result
// seam is a deterministic failure (guardrail).
using ToolExecutionBoundary = std::function<std::string(
    const ak::tool::CapabilityId&, const std::string& /* payload */)>;

// Construction/injection values for FirstWorkingAgentComposition.
struct FirstWorkingAgentConfiguration {
    ak::agent::AgentIdentity agent_identity;
    ak::planner::PlannerIdentity planner_identity;
    ak::planner::PlannerConfiguration planner_config;
    ak::prompt::PromptDefinition prompt_definition;
    ak::tool::ToolId tool_id;
    ak::tool::ToolConfiguration tool_config;
    std::vector<std::unique_ptr<ak::tool::IToolProvider>> tool_providers;
    ak::context::ContextIdentity context_identity;
    ak::memory::MemoryIdentity memory_identity;
    ModelBoundary model_boundary;              // required for Run()
    ToolExecutionBoundary tool_execution_boundary;  // test-scoped seam
    std::size_t max_cycles = 8;                // deterministic loop bound
};

}  // namespace ak::agent
