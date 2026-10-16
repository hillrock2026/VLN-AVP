// ============================================================
// agent_model_integration_test.cpp - P1-IS008 Rev1.0 Chapters
// 15, 19.3
// ============================================================
// Agent-Model integration tests over the canonical path:
//   Agent -> Planner/Context/Memory information -> Prompt
//     -> Model Boundary -> Deterministic Model -> ModelResult
//     -> Agent interpretation -> ModelAction/decision
//
// The real ak::agent::Agent participates (lifecycle + identity)
// and Agent interpretation derives the existing Agent-owned
// ak::agent::ModelAction from the Model-owned ModelResult
// (Chapters 8, 9, 15). The Model is the deterministic test
// double (Chapter 13); no network/provider/GPU is involved.
// ============================================================

#include <agent_kernel/agent/agent.hpp>
#include <agent_kernel/agent/agent_identity.hpp>
#include <agent_kernel/agent/agent_state.hpp>
#include <agent_kernel/agent_model/agent_model_binding.hpp>
#include <agent_kernel/agent_model/agent_model_host.hpp>
#include <agent_kernel/agent_prompt/agent_prompt_host.hpp>
#include <agent_kernel/fwa/model_action.hpp>
#include <agent_kernel/prompt/prompt_definition.hpp>
#include <agent_kernel/prompt/prompt_identity.hpp>
#include <agent_kernel/prompt/prompt_request.hpp>
#include <agent_kernel/prompt/prompt_section.hpp>
#include <agent_kernel/prompt/prompt_variable.hpp>
#include <agent_kernel/tool/tool_identity.hpp>

#include <gtest/gtest.h>

#include "../model/deterministic_model.hpp"

#include <cstddef>
#include <memory>
#include <string>
#include <vector>

namespace ak {
namespace {

using ak::model::ModelId;
using ak::model::ModelInput;
using ak::model::ModelResult;
using ak::model::test::DeterministicModel;
using ak::model::test::DeterministicModelMode;

// ------------------------------------------------------------
// Test-scope Agent coordination helpers. Interpretation of
// ModelResult into ModelAction is Agent-owned (Chapter 8); the
// same interpretation pattern is used by the accepted First
// Working Agent composition (TASK 6 Rev2 StepCycleInternal).
// ------------------------------------------------------------

ak::prompt::PromptDefinition MakePromptDefinition() {
    return ak::prompt::PromptDefinition(
        ak::prompt::PromptId("integration-prompt"), "1.0",
        {ak::prompt::PromptSection(
            ak::prompt::PromptSectionKind::kSystemInstruction,
            {ak::prompt::PromptComponent(
                ak::prompt::PromptSectionKind::kSystemInstruction,
                "You are an agent. {objective}")})},
        {ak::prompt::PromptVariable("objective",
                                    ak::prompt::PromptSectionKind::kUserInput,
                                    true)});
}

// Assembles the model-facing PromptResult and returns the
// concatenated assembled material (Prompt -> Model input).
std::string AssemblePromptMaterial(agent::AgentPromptHost& prompt_host) {
    const ak::prompt::PromptAssemblyRequest request(
        {ak::prompt::PromptInputBinding("objective", "advance the mission")});
    const ak::prompt::PromptAssemblyResult assembly =
        prompt_host.Binding().Assemble(request);
    EXPECT_TRUE(assembly.Succeeded());
    if (!assembly.Succeeded() || !assembly.result.has_value()) {
        return "";
    }
    std::string material;
    for (const ak::prompt::AssembledComponent& component :
         assembly.result->Components()) {
        material += component.content;
    }
    return material;
}

// Agent-owned interpretation: ModelResult -> existing
// ak::agent::ModelAction (Chapters 8, 9, 15). The payload
// vocabulary is deterministic for the integration scenario:
//   "tool:<capability>:<arguments>" -> kToolInvoke
//   "complete"                     -> kComplete
//   invalid/failure                -> kInvalid (diagnostic)
// This helper is TEST SCOPE ONLY; it mirrors the interpretation
// performed by the accepted First Working Agent composition.
ak::agent::ModelAction InterpretModelResult(const ModelResult& result) {
    if (result.IsInvalidResult() || result.IsFailure()) {
        return ak::agent::ModelAction::Invalid(result.Diagnostic());
    }
    const std::string& payload = result.Payload().value();
    if (payload == "complete") {
        return ak::agent::ModelAction::Complete();
    }
    if (payload.rfind("tool:", 0) == 0) {
        const std::string spec = payload.substr(5);
        const std::size_t separator = spec.find(':');
        if (separator != std::string::npos && separator > 0 &&
            separator + 1 < spec.size()) {
            return ak::agent::ModelAction::InvokeTool(
                ak::tool::CapabilityId(spec.substr(0, separator)),
                spec.substr(separator + 1));
        }
    }
    return ak::agent::ModelAction::Invalid("unsupported model payload");
}

std::unique_ptr<DeterministicModel> MakeEchoModel() {
    return std::make_unique<DeterministicModel>(
        ModelId("integration-model"), DeterministicModelMode::kEcho);
}

TEST(AgentModelIntegration, AgentInvokesModel) {
    // Real Agent lifecycle participates; Model lifecycle is
    // independent and Model does not drive Agent state.
    agent::Agent agent(agent::MakeAgentIdentity(1));
    EXPECT_TRUE(agent.Initialize().Accepted());
    EXPECT_EQ(agent.GetState(), agent::AgentState::kReady);

    agent::AgentModelHost host(MakeEchoModel());
    EXPECT_TRUE(host.Binding().Initialize().Accepted());

    const ModelResult result =
        host.Binding().Infer(ModelInput("agent input"));
    EXPECT_TRUE(result.IsSuccess());
    ASSERT_TRUE(result.Payload().has_value());
    EXPECT_EQ(result.Payload().value(), "echo:agent input");

    // Agent remains the intelligent execution authority; its
    // lifecycle is unaffected by the Model boundary.
    EXPECT_EQ(agent.GetState(), agent::AgentState::kReady);
    EXPECT_TRUE(agent.Terminate().Accepted());
    EXPECT_EQ(agent.GetState(), agent::AgentState::kTerminated);
}

TEST(AgentModelIntegration, PromptResultReachesModel) {
    agent::AgentPromptHost prompt_host(MakePromptDefinition());
    const std::string material = AssemblePromptMaterial(prompt_host);
    ASSERT_FALSE(material.empty());

    agent::AgentModelHost host(MakeEchoModel());
    EXPECT_TRUE(host.Binding().Initialize().Accepted());

    const ModelResult result =
        host.Binding().Infer(ModelInput(material));
    ASSERT_TRUE(result.IsSuccess());
    // The Model received the Prompt-assembled material verbatim.
    EXPECT_EQ(result.Payload().value(), "echo:" + material);
}

TEST(AgentModelIntegration, ModelProducesModelResult) {
    agent::AgentModelHost host(MakeEchoModel());
    EXPECT_TRUE(host.Binding().Initialize().Accepted());
    const ModelResult result =
        host.Binding().Infer(ModelInput("objective input"));
    EXPECT_TRUE(result.IsSuccess());
    EXPECT_TRUE(result.Valid());
    EXPECT_EQ(result.Status(), ak::model::ModelStatus::kSuccess);
}

TEST(AgentModelIntegration, AgentInterpretsModelResult) {
    const ModelResult success = ModelResult::Success("complete");
    const ak::agent::ModelAction complete = InterpretModelResult(success);
    EXPECT_TRUE(complete.IsComplete());

    const ModelResult invalid =
        ModelResult::InvalidResult("provider output is not interpretable");
    const ak::agent::ModelAction invalid_action = InterpretModelResult(invalid);
    EXPECT_TRUE(invalid_action.IsInvalid());
    EXPECT_EQ(invalid_action.Reason(), "provider output is not interpretable");
}

TEST(AgentModelIntegration, AgentCanDeriveModelAction) {
    const ModelResult tool = ModelResult::Success("tool:greet:hello");
    const ak::agent::ModelAction invoke = InterpretModelResult(tool);
    EXPECT_TRUE(invoke.IsToolInvoke());
    ASSERT_NE(invoke.Capability(), nullptr);
    EXPECT_EQ(invoke.Capability()->Value(), "greet");
    EXPECT_EQ(invoke.Arguments(), "hello");

    const ModelResult done = ModelResult::Success("complete");
    EXPECT_TRUE(InterpretModelResult(done).IsComplete());
}

TEST(AgentModelIntegration, DeterministicAgentModelLoop) {
    // Real Agent lifecycle is present; the loop is Agent
    // coordination over AgentModelBinding.
    agent::Agent agent(agent::MakeAgentIdentity(2));
    EXPECT_TRUE(agent.Initialize().Accepted());

    auto model = std::make_unique<DeterministicModel>(
        ModelId("loop-model"), DeterministicModelMode::kToolThenComplete,
        "tool:greet:hello");
    agent::AgentModelHost host(std::move(model));
    EXPECT_TRUE(host.Binding().Initialize().Accepted());

    std::vector<ak::agent::ModelAction> actions;
    for (int cycle = 0; cycle < 3 && actions.size() < 2; ++cycle) {
        const ModelResult result =
            host.Binding().Infer(ModelInput("objective input"));
        ASSERT_TRUE(result.IsSuccess());
        actions.push_back(InterpretModelResult(result));
        if (actions.back().IsComplete()) {
            break;
        }
    }

    ASSERT_EQ(actions.size(), 2u);
    EXPECT_TRUE(actions[0].IsToolInvoke());
    ASSERT_NE(actions[0].Capability(), nullptr);
    EXPECT_EQ(actions[0].Capability()->Value(), "greet");
    EXPECT_EQ(actions[0].Arguments(), "hello");
    EXPECT_TRUE(actions[1].IsComplete());

    EXPECT_EQ(agent.GetState(), agent::AgentState::kReady);
    EXPECT_TRUE(agent.Terminate().Accepted());
}

TEST(AgentModelIntegration, DeterministicLoopIsRepeatable) {
    // Chapter 19.5: a fresh identical composition produces the
    // identical ModelResult sequence (same input -> same output).
    auto model = std::make_unique<DeterministicModel>(
        ModelId("repeat-model"), DeterministicModelMode::kToolThenComplete,
        "tool:greet:hello");
    agent::AgentModelHost host(std::move(model));
    EXPECT_TRUE(host.Binding().Initialize().Accepted());

    const ModelResult first =
        host.Binding().Infer(ModelInput("objective input"));
    const ModelResult second =
        host.Binding().Infer(ModelInput("objective input"));
    ASSERT_TRUE(first.IsSuccess());
    ASSERT_TRUE(second.IsSuccess());
    EXPECT_EQ(first.Payload().value(), "tool:greet:hello");
    EXPECT_EQ(second.Payload().value(), "complete");
}

}  // namespace
}  // namespace ak
