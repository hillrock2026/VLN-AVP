// ============================================================
// first_working_agent_integration_test.cpp - First Working
// Agent Sprint E2E tests (FWA-001..FWA-004)
// ============================================================
// TASK 6 Rev2 闁?8: proves Agent Kernel integration, NOT a model
// SDK, Tool SDK, or Runtime implementation.
//
//   Objective -> Agent -> Planner -> Prompt -> Deterministic
//   Model -> ModelAction -> Tool -> Observation -> Context
//   Update -> Completion
//
// FWA-T7 / TASK-6-Rev2 / STEP-13 / AC-001..AC-019
// ============================================================

#include <agent_kernel/agent/agent.hpp>
#include <agent_kernel/fwa/first_working_agent_composition.hpp>
#include <agent_kernel/fwa/first_working_agent_configuration.hpp>
#include <agent_kernel/context/context_identity.hpp>
#include <agent_kernel/memory/memory_identity.hpp>
#include <agent_kernel/memory/memory_state.hpp>
#include <agent_kernel/planner/planner_identity.hpp>
#include <agent_kernel/prompt/prompt_definition.hpp>
#include <agent_kernel/prompt/prompt_request.hpp>
#include <agent_kernel/prompt/prompt_section.hpp>
#include <agent_kernel/prompt/prompt_variable.hpp>
#include <agent_kernel/tool/tool_identity.hpp>

#include <gtest/gtest.h>

#include <memory>
#include <string>

#include "deterministic_test_executor.hpp"
#include "deterministic_test_model.hpp"
#include "deterministic_test_provider.hpp"

namespace ak::agent {
namespace test {
namespace {

constexpr const char* kCapabilityId = "fwa-capability";
constexpr const char* kProviderId = "fwa-provider";
constexpr const char* kObjectiveText = "Perform the predefined test action.";

// ------------------------------------------------------------
// Deterministic FWA prompt definition (declared variables match
// the composition's material translation categories).
// ------------------------------------------------------------
ak::prompt::PromptDefinition MakeFwaPromptDefinition() {
    return ak::prompt::PromptDefinition(
        ak::prompt::PromptId("fwa-prompt"), "1.0",
        {ak::prompt::PromptSection(
             ak::prompt::PromptSectionKind::kSystemInstruction,
             {ak::prompt::PromptComponent(
                 ak::prompt::PromptSectionKind::kSystemInstruction,
                 "You are the First Working Agent.")}),
         ak::prompt::PromptSection(
             ak::prompt::PromptSectionKind::kContextMaterial,
             {ak::prompt::PromptComponent(
                 ak::prompt::PromptSectionKind::kContextMaterial,
                 "Context: {context_snapshot}")}),
         ak::prompt::PromptSection(
             ak::prompt::PromptSectionKind::kMemoryMaterial,
             {ak::prompt::PromptComponent(
                 ak::prompt::PromptSectionKind::kMemoryMaterial,
                 "Memory: {memory_material}")}),
         ak::prompt::PromptSection(
             ak::prompt::PromptSectionKind::kPlanningMaterial,
             {ak::prompt::PromptComponent(
                 ak::prompt::PromptSectionKind::kPlanningMaterial,
                 "Plan: {plan_summary}")}),
         ak::prompt::PromptSection(
             ak::prompt::PromptSectionKind::kToolMaterial,
             {ak::prompt::PromptComponent(
                 ak::prompt::PromptSectionKind::kToolMaterial,
                 "Tools: {tool_capabilities}")}),
         ak::prompt::PromptSection(
             ak::prompt::PromptSectionKind::kUserInput,
             {ak::prompt::PromptComponent(
                 ak::prompt::PromptSectionKind::kUserInput,
                 "User: {user_input}")})},
        {ak::prompt::PromptVariable(
             "context_snapshot",
             ak::prompt::PromptSectionKind::kContextMaterial, true),
         ak::prompt::PromptVariable(
             "memory_material",
             ak::prompt::PromptSectionKind::kMemoryMaterial, true),
         ak::prompt::PromptVariable(
             "plan_summary",
             ak::prompt::PromptSectionKind::kPlanningMaterial, true),
         ak::prompt::PromptVariable(
             "tool_capabilities",
             ak::prompt::PromptSectionKind::kToolMaterial, true),
         ak::prompt::PromptVariable(
             "user_input", ak::prompt::PromptSectionKind::kUserInput,
             true)});
}

// ------------------------------------------------------------
// Configuration factory (deterministic doubles)
// ------------------------------------------------------------
FirstWorkingAgentConfiguration MakeConfiguration(
    DeterministicTestModel* model, bool tool_preparation_failure = false,
    bool configure_executor = true) {
    std::vector<std::unique_ptr<ak::tool::IToolProvider>> providers;
    providers.push_back(std::make_unique<DeterministicTestProvider>(
        kProviderId, kCapabilityId, tool_preparation_failure));
    FirstWorkingAgentConfiguration config{
        .agent_identity = ak::agent::MakeAgentIdentity(1),
        .planner_identity = ak::planner::MakePlannerIdentity(1),
        .planner_config = ak::planner::PlannerConfiguration{},
        .prompt_definition = MakeFwaPromptDefinition(),
        .tool_id = ak::tool::ToolId("fwa-tool"),
        .tool_config = ak::tool::ToolConfiguration{
            "fwa-tool", "1.0", "FWA Tool"},
        .tool_providers = std::move(providers),
        .context_identity = ak::context::MakeContextIdentity(1),
        .memory_identity = ak::memory::MakeMemoryIdentity(1),
        .model_boundary =
            [model](const ak::prompt::PromptResult& result) {
                return (*model)(result);
            },
        .tool_execution_boundary = configure_executor
            ? ToolExecutionBoundary(&DeterministicTestExecutor)
            : ToolExecutionBoundary{},
        .max_cycles = 8,
    };
    return config;
}

ExecutionObjective MakeObjective() {
    return ExecutionObjective(ObjectiveId(1), kObjectiveText);
}

// Reads the single FWA Context Object content (observability).
std::string ReadContextContent(FirstWorkingAgentComposition& composition) {
    const ak::context::ContextResultValue<
        std::vector<ak::context::ContextObjectId>>
        objects =
            composition.Context().AgentContract().Access().ListObjects();
    EXPECT_TRUE(objects.IsSuccess());
    EXPECT_EQ(objects.value.size(), 1u);
    if (objects.value.empty()) {
        return "";
    }
    const ak::context::ContextResultValue<ak::context::ContextObjectView> view =
        composition.Context().AgentContract().Access().InspectObject(
            objects.value[0]);
    EXPECT_TRUE(view.IsSuccess());
    return view.value.content;
}

// ------------------------------------------------------------
// FWA-001 闂?complete working Agent cycle (positive)
// ------------------------------------------------------------
TEST(FirstWorkingAgentIntegration, FWA_001_CompleteWorkingAgentCycle) {
    DeterministicTestModel model(ak::tool::CapabilityId(kCapabilityId),
                                 "payload",
                                 DeterministicModelMode::kToolThenComplete);
    FirstWorkingAgentComposition composition(MakeConfiguration(&model));

    // AC-001: Agent receives objective.
    const ExecutionObjective objective = MakeObjective();
    ASSERT_TRUE(composition.Initialize(objective));
    ASSERT_NE(composition.Agent().FindObjective(objective.GetId()), nullptr);

    // AC-002: Context is available.
    EXPECT_EQ(composition.Context().AgentContract().Creation().ObjectCount(),
              1u);
    EXPECT_EQ(ReadContextContent(composition), "initial context");

    // AC-003: Memory interaction is available (lifecycle
    // participation + retrieval material reaches the Prompt).
    EXPECT_EQ(composition.Memory().GetLifecycleState(),
              ak::memory::MemoryLifecycleState::kActive);

    // Cycle 1: planning -> prompt -> model(kToolInvoke) -> Tool
    // preparation -> test executor -> Context update.
    const CycleOutcome first = composition.StepCycle();
    EXPECT_FALSE(first.completed);
    EXPECT_EQ(first.summary, "fwa-cycle-tool-invocation");
    // AC-007: Agent interpreted kToolInvoke.
    // AC-008: capability discoverable; AC-009: preparation
    // succeeded 闂?observable in the deterministic diagnostics.
    EXPECT_NE(first.diagnostics.find("tool:prepared"), std::string::npos);
    EXPECT_EQ(model.call_count(), 1u);

    // AC-010/AC-011: observation represented as a Context Object
    // value; Context update succeeded.
    EXPECT_NE(ReadContextContent(composition).find("[tool-result]"),
              std::string::npos);

    // Cycle 2: model(kComplete) -> completion evaluation.
    const CycleOutcome second = composition.StepCycle();
    EXPECT_TRUE(second.completed);
    EXPECT_EQ(second.summary, "fwa-cycle-completed");
    // AC-012: kComplete terminates the FWA cycle.
    EXPECT_EQ(model.call_count(), 2u);
    // AC-004: Planner produced a planning result (the plan
    // material reached the Prompt).
    EXPECT_NE(model.last_prompt_material().find(std::string("Plan: ") +
                                                kObjectiveText),
              std::string::npos);
    // AC-005: Prompt produced a PromptResult (assembled material).
    EXPECT_NE(model.last_prompt_material().find("Context: [tool-result]"),
              std::string::npos);
    // AC-006: deterministic Model boundary returned ModelAction.
    // AC-013/014/015/016: no invalid/failure; no Runtime; the
    // existing Tool root + AgentToolBinding are reused.
    // AC-019: FWA E2E completed; legal non-Terminated final state
    // (OBS-02 default ending after EvaluateObjective).
    EXPECT_EQ(composition.Agent().GetState(),
              ak::agent::AgentState::kCoordinating);
}

// ------------------------------------------------------------
// FWA-002 闂?invalid ModelAction (negative 1)
// ------------------------------------------------------------
TEST(FirstWorkingAgentIntegration, FWA_002_InvalidModelActionIsDeterministic) {
    DeterministicTestModel model(ak::tool::CapabilityId(kCapabilityId),
                                 "payload", DeterministicModelMode::kInvalid,
                                 "malformed output");
    FirstWorkingAgentComposition composition(MakeConfiguration(&model));
    ASSERT_TRUE(composition.Initialize(MakeObjective()));

    const CycleOutcome outcome = composition.Run();

    // AC-013: kInvalid is handled deterministically: no Tool call,
    // deterministic end, no invalid Context mutation.
    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.summary, "fwa-cycle-invalid");
    EXPECT_NE(outcome.diagnostics.find("reason:malformed output"),
              std::string::npos);
    EXPECT_EQ(ReadContextContent(composition), "initial context");
    EXPECT_EQ(model.call_count(), 1u);
    EXPECT_TRUE(composition.Agent().Diagnostics().HasErrors());
}

// ------------------------------------------------------------
// FWA-003 闂?Tool preparation failure (negative 2a)
// ------------------------------------------------------------
TEST(FirstWorkingAgentIntegration, FWA_003_ToolPreparationFailureIsDeterministic) {
    DeterministicTestModel model(ak::tool::CapabilityId(kCapabilityId),
                                 "payload",
                                 DeterministicModelMode::kToolThenComplete);
    FirstWorkingAgentComposition composition(
        MakeConfiguration(&model, /*tool_preparation_failure=*/true));
    ASSERT_TRUE(composition.Initialize(MakeObjective()));

    const CycleOutcome outcome = composition.Run();

    // AC-014: Tool preparation failure is handled deterministically:
    // observable failure, correct Context semantics (no mutation),
    // deterministic termination (no retry).
    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.summary, "fwa-cycle-failure");
    EXPECT_NE(outcome.diagnostics.find("tool-preparation-failure:"),
              std::string::npos);
    EXPECT_EQ(ReadContextContent(composition), "initial context");
    EXPECT_EQ(model.call_count(), 1u);
}

// ------------------------------------------------------------
// FWA-003 闂?test executor failure (negative 2b; OBS-03 guardrail)
// ------------------------------------------------------------
TEST(FirstWorkingAgentIntegration, FWA_003_UnconfiguredExecutorIsDeterministicFailure) {
    DeterministicTestModel model(ak::tool::CapabilityId(kCapabilityId),
                                 "payload",
                                 DeterministicModelMode::kToolThenComplete);
    FirstWorkingAgentComposition composition(
        MakeConfiguration(&model, /*tool_preparation_failure=*/false,
                          /*configure_executor=*/false));
    ASSERT_TRUE(composition.Initialize(MakeObjective()));

    const CycleOutcome outcome = composition.Run();

    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.summary, "fwa-cycle-failure");
    EXPECT_NE(outcome.diagnostics.find(
                  "tool-execution-boundary-not-configured"),
              std::string::npos);
    EXPECT_EQ(ReadContextContent(composition), "initial context");
}

// ------------------------------------------------------------
// FWA-004 闂?direct completion without Tool (negative 3)
// ------------------------------------------------------------
TEST(FirstWorkingAgentIntegration, FWA_004_DirectCompletionWithoutTool) {
    DeterministicTestModel model(ak::tool::CapabilityId(kCapabilityId),
                                 "payload",
                                 DeterministicModelMode::kCompleteFirst);
    FirstWorkingAgentComposition composition(MakeConfiguration(&model));
    ASSERT_TRUE(composition.Initialize(MakeObjective()));

    const CycleOutcome outcome = composition.Run();

    // AC-012/AC-019: kComplete terminates; Tool path never entered.
    EXPECT_TRUE(outcome.completed);
    EXPECT_EQ(outcome.summary, "fwa-cycle-completed");
    EXPECT_EQ(model.call_count(), 1u);
    EXPECT_EQ(ReadContextContent(composition), "initial context");
}

// ------------------------------------------------------------
// max_cycles exhaustion (TASK 6 Rev2 闁?3) 闂?deterministic
// "not completed" outcome.
// ------------------------------------------------------------
TEST(FirstWorkingAgentIntegration, MaxCyclesExhaustionIsDeterministic) {
    DeterministicTestModel model(ak::tool::CapabilityId(kCapabilityId),
                                 "payload",
                                 DeterministicModelMode::kAlwaysTool);
    FirstWorkingAgentConfiguration config = MakeConfiguration(&model);
    config.max_cycles = 3;
    FirstWorkingAgentComposition composition(std::move(config));
    ASSERT_TRUE(composition.Initialize(MakeObjective()));

    const CycleOutcome outcome = composition.Run();

    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.summary, "fwa-cycle-max-cycles-exhausted");
    EXPECT_EQ(model.call_count(), 3u);
}

// ------------------------------------------------------------
// Determinism (TASK 6 Rev2 闁?0): identical input + deterministic
// doubles => identical outcome across runs.
// ------------------------------------------------------------
TEST(FirstWorkingAgentIntegration, DeterminismTwoRunsProduceIdenticalOutcome) {
    const auto run_once = [](std::string& context_out) {
        DeterministicTestModel model(ak::tool::CapabilityId(kCapabilityId),
                                     "payload",
                                     DeterministicModelMode::kToolThenComplete);
        FirstWorkingAgentComposition composition(MakeConfiguration(&model));
        const ExecutionObjective objective = MakeObjective();
        const bool initialized = composition.Initialize(objective);
        const CycleOutcome outcome = composition.Run();
        context_out = ReadContextContent(composition);
        return std::make_tuple(initialized, outcome.completed, outcome.summary,
                               outcome.diagnostics,
                               composition.Agent().GetState());
    };

    std::string context_run1;
    std::string context_run2;
    const auto run1 = run_once(context_run1);
    const auto run2 = run_once(context_run2);

    EXPECT_EQ(std::get<0>(run1), std::get<0>(run2));
    EXPECT_EQ(std::get<1>(run1), std::get<1>(run2));
    EXPECT_EQ(std::get<2>(run1), std::get<2>(run2));
    EXPECT_EQ(std::get<3>(run1), std::get<3>(run2));
    EXPECT_EQ(std::get<4>(run1), std::get<4>(run2));
    EXPECT_EQ(context_run1, context_run2);
}

}  // namespace
}  // namespace test
}  // namespace ak::agent
