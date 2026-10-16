// ============================================================
// prompt_assembly_test.cpp - P1-IS007 Rev1.1 Chapter 33
// ============================================================
// Assembly tests: single assembly entry (PRM-040), ordered
// section/component assembly (PRM-010), variable substitution,
// deterministic output (PRM-014, PRM-041, AC-006), and
// immutable PromptResult construction (PRM-042).
// ============================================================

#include <agent_kernel/prompt/prompt.hpp>
#include <agent_kernel/prompt/prompt_request.hpp>
#include <agent_kernel/prompt/prompt_result.hpp>

#include <gtest/gtest.h>

#include <cstddef>
#include <string>
#include <vector>

namespace ak::prompt {
namespace {

Prompt BuildMultiSectionPrompt() {
    return Prompt(PromptDefinition(
        PromptId("multi-section"),
        "1.0",
        {PromptSection(
             PromptSectionKind::kSystemInstruction,
             {PromptComponent(PromptSectionKind::kSystemInstruction,
                              "You are a helpful agent.")}),
         PromptSection(
             PromptSectionKind::kContextMaterial,
             {PromptComponent(PromptSectionKind::kContextMaterial,
                              "Context: {context_snapshot}")}),
         PromptSection(
             PromptSectionKind::kUserInput,
             {PromptComponent(PromptSectionKind::kUserInput,
                              "User: {user_input}")})},
        {PromptVariable("context_snapshot",
                        PromptSectionKind::kContextMaterial, true),
         PromptVariable("user_input", PromptSectionKind::kUserInput, true)}));
}

TEST(PromptAssembly, PRM_040_SingleAssemblyEntry) {
    // The public surface exposes exactly one production
    // assembly operation (Chapters 24.1, 41.1): no partial,
    // incremental, streaming, or subsystem-specific operations
    // exist.
    Prompt prompt = BuildMultiSectionPrompt();
    const PromptAssemblyRequest request(
        {PromptInputBinding("context_snapshot", "working state"),
         PromptInputBinding("user_input", "hello")});
    const PromptAssemblyResult result = prompt.Assembly().Assemble(request);
    ASSERT_TRUE(result.Succeeded());
    ASSERT_TRUE(result.result.has_value());
    EXPECT_EQ(result.result->Id(), PromptId("multi-section"));
    EXPECT_EQ(result.result->DefinitionVersion(), "1.0");
}

TEST(PromptAssembly, PRM_010_OrderedSectionsAndComponents) {
    Prompt prompt = BuildMultiSectionPrompt();
    const PromptAssemblyRequest request(
        {PromptInputBinding("context_snapshot", "working state"),
         PromptInputBinding("user_input", "hello")});
    const PromptAssemblyResult result = prompt.Assembly().Assemble(request);
    ASSERT_TRUE(result.Succeeded());
    const std::vector<AssembledComponent>& components =
        result.result->Components();
    ASSERT_EQ(components.size(), 3u);
    EXPECT_EQ(components[0].kind, PromptSectionKind::kSystemInstruction);
    EXPECT_EQ(components[0].content, "You are a helpful agent.");
    EXPECT_EQ(components[1].kind, PromptSectionKind::kContextMaterial);
    EXPECT_EQ(components[1].content, "Context: working state");
    EXPECT_EQ(components[2].kind, PromptSectionKind::kUserInput);
    EXPECT_EQ(components[2].content, "User: hello");
}

TEST(PromptAssembly, PRM_014_DeterministicOutput) {
    Prompt prompt = BuildMultiSectionPrompt();
    const PromptAssemblyRequest request(
        {PromptInputBinding("context_snapshot", "working state"),
         PromptInputBinding("user_input", "hello")});
    const PromptAssemblyResult first = prompt.Assembly().Assemble(request);
    const PromptAssemblyResult second = prompt.Assembly().Assemble(request);
    ASSERT_TRUE(first.Succeeded());
    ASSERT_TRUE(second.Succeeded());
    EXPECT_EQ(first.result->Components().size(),
              second.result->Components().size());
    for (std::size_t i = 0; i < first.result->Components().size(); ++i) {
        EXPECT_EQ(first.result->Components()[i].kind,
                  second.result->Components()[i].kind);
        EXPECT_EQ(first.result->Components()[i].content,
                  second.result->Components()[i].content);
    }
}

TEST(PromptAssembly, PRM_014_OptionalUnboundVariableSubstitutesEmpty) {
    Prompt prompt = Prompt(PromptDefinition(
        PromptId("optional-prompt"), "1.0",
        {PromptSection(
            PromptSectionKind::kUserInput,
            {PromptComponent(PromptSectionKind::kUserInput,
                             "Optional: {optional_material}")})},
        {PromptVariable("optional_material",
                        PromptSectionKind::kAdditionalContext, false)}));
    const PromptAssemblyResult result =
        prompt.Assembly().Assemble(PromptAssemblyRequest());
    ASSERT_TRUE(result.Succeeded());
    ASSERT_EQ(result.result->Components().size(), 1u);
    EXPECT_EQ(result.result->Components()[0].content, "Optional: ");
}

TEST(PromptAssembly, PRM_042_ResultImmutability) {
    Prompt prompt = BuildMultiSectionPrompt();
    const PromptAssemblyRequest request(
        {PromptInputBinding("context_snapshot", "working state"),
         PromptInputBinding("user_input", "hello")});
    const PromptAssemblyResult result = prompt.Assembly().Assemble(request);
    ASSERT_TRUE(result.Succeeded());
    const PromptResult& immutable = *result.result;
    EXPECT_EQ(immutable.ValidationStatus(), PromptValidationStatus::kValid);
    // Accessors are const; the result exposes no mutating API.
    EXPECT_EQ(immutable.Components()[0].content, "You are a helpful agent.");
}

}  // namespace
}  // namespace ak::prompt