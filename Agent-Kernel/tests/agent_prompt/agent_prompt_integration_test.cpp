// ============================================================
// agent_prompt_integration_test.cpp - P1-IS007 Rev1.1 Chapter
// 33, canonical data flow (Chapter 40)
// ============================================================
// Production composition tests using REAL production objects:
//
//   Agent
//     -> AgentPromptHost
//     -> AgentPromptBinding
//     -> Prompt
//     -> PromptResult (Future Model boundary)
//
// No test double substitutes for the production Prompt root in
// the primary composition test (PRM-023, PRM-039, AC-009,
// AC-030).
// ============================================================

#include <agent_kernel/agent_prompt/agent_prompt_binding.hpp>
#include <agent_kernel/agent_prompt/agent_prompt_host.hpp>
#include <agent_kernel/prompt/prompt.hpp>
#include <agent_kernel/prompt/prompt_request.hpp>
#include <agent_kernel/prompt/prompt_result.hpp>

#include <gtest/gtest.h>

#include <cstddef>
#include <string>
#include <vector>

namespace ak::agent {
namespace {

ak::prompt::PromptDefinition MakeAgentDefinition() {
    return ak::prompt::PromptDefinition(
        ak::prompt::PromptId("agent-prompt"), "1.0",
        {ak::prompt::PromptSection(
             ak::prompt::PromptSectionKind::kSystemInstruction,
             {ak::prompt::PromptComponent(
                 ak::prompt::PromptSectionKind::kSystemInstruction,
                 "You are an agent.")}),
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

ak::prompt::PromptAssemblyRequest MakeAgentRequest() {
    return ak::prompt::PromptAssemblyRequest(
        {ak::prompt::PromptInputBinding("context_snapshot", "working state"),
         ak::prompt::PromptInputBinding("memory_material", "retained fact"),
         ak::prompt::PromptInputBinding("plan_summary", "step 1"),
         ak::prompt::PromptInputBinding("tool_capabilities", "capability-a"),
         ak::prompt::PromptInputBinding("user_input", "hello")});
}

TEST(AgentPromptIntegration, AC_009_RealAgentToPromptComposition) {
    AgentPromptHost host(MakeAgentDefinition());
    const AgentPromptBinding& binding = host.Binding();
    const ak::prompt::PromptAssemblyResult result =
        binding.Assemble(MakeAgentRequest());
    ASSERT_TRUE(result.Succeeded());
    ASSERT_TRUE(result.result.has_value());
    EXPECT_EQ(result.result->Id(), ak::prompt::PromptId("agent-prompt"));
    EXPECT_EQ(result.result->DefinitionVersion(), "1.0");

    const std::vector<ak::prompt::AssembledComponent>& components =
        result.result->Components();
    ASSERT_EQ(components.size(), 6u);
    EXPECT_EQ(components[0].content, "You are an agent.");
    EXPECT_EQ(components[1].content, "Context: working state");
    EXPECT_EQ(components[2].content, "Memory: retained fact");
    EXPECT_EQ(components[3].content, "Plan: step 1");
    EXPECT_EQ(components[4].content, "Tools: capability-a");
    EXPECT_EQ(components[5].content, "User: hello");
}

TEST(AgentPromptIntegration, PRM_039_EstablishedCompositionPattern) {
    // The composition root owns the Prompt root and the
    // non-owning binding view (P1-IS005 / P1-IS006 Rev2
    // pattern); the Agent coordinates Prompt exclusively
    // through the binding (PRM-039, AC-030).
    AgentPromptHost host(MakeAgentDefinition());
    AgentPromptBinding& binding = host.Binding();
    EXPECT_EQ(binding.Definition().Id(),
              ak::prompt::PromptId("agent-prompt"));
    const ak::prompt::PromptAssemblyResult result =
        binding.Assemble(MakeAgentRequest());
    EXPECT_TRUE(result.Succeeded());
}

TEST(AgentPromptIntegration, PRM_014_EndToEndDeterminism) {
    AgentPromptHost host(MakeAgentDefinition());
    const AgentPromptBinding& binding = host.Binding();
    const ak::prompt::PromptAssemblyResult first =
        binding.Assemble(MakeAgentRequest());
    const ak::prompt::PromptAssemblyResult second =
        binding.Assemble(MakeAgentRequest());
    ASSERT_TRUE(first.Succeeded());
    ASSERT_TRUE(second.Succeeded());
    ASSERT_EQ(first.result->Components().size(),
              second.result->Components().size());
    for (std::size_t i = 0; i < first.result->Components().size(); ++i) {
        EXPECT_EQ(first.result->Components()[i].content,
                  second.result->Components()[i].content);
    }
}

TEST(AgentPromptIntegration, PRM_043_ErrorPropagationThroughBinding) {
    AgentPromptHost host(MakeAgentDefinition());
    const AgentPromptBinding& binding = host.Binding();
    const ak::prompt::PromptAssemblyResult result =
        binding.Assemble(ak::prompt::PromptAssemblyRequest());
    EXPECT_FALSE(result.Succeeded());
    EXPECT_EQ(result.status,
              ak::prompt::PromptAssemblyStatus::kUnavailableRequiredMaterial);
}

}  // namespace
}  // namespace ak::agent