// ============================================================
// prompt_validation_test.cpp - P1-IS007 Rev1.1 Chapter 33
// ============================================================
// Validation and error tests: the deterministic error model
// (PRM-013, PRM-043, AC-005, Chapter 25) and deterministic
// error propagation (Chapter 41.4).
// ============================================================

#include <agent_kernel/prompt/prompt.hpp>
#include <agent_kernel/prompt/prompt_request.hpp>
#include <agent_kernel/prompt/prompt_result.hpp>

#include <gtest/gtest.h>

#include <stdexcept>
#include <string>

namespace ak::prompt {
namespace {

Prompt BuildPromptWithRequired(const char* variable_name,
                               PromptSectionKind category) {
    return Prompt(PromptDefinition(
        PromptId("validated-prompt"), "1.0",
        {PromptSection(
            category,
            {PromptComponent(category, std::string("content for {") +
                                           variable_name + "}")})},
        {PromptVariable(variable_name, category, true)}));
}

TEST(PromptValidation, PRM_043_UnavailableRequiredMaterial) {
    Prompt prompt = BuildPromptWithRequired(
        "memory_material", PromptSectionKind::kMemoryMaterial);
    const PromptAssemblyResult result =
        prompt.Assembly().Assemble(PromptAssemblyRequest());
    EXPECT_FALSE(result.Succeeded());
    EXPECT_EQ(result.status,
              PromptAssemblyStatus::kUnavailableRequiredMaterial);
    EXPECT_EQ(result.variable, "memory_material");
    EXPECT_FALSE(result.result.has_value());
}

TEST(PromptValidation, PRM_043_MissingRequiredInput) {
    Prompt prompt = BuildPromptWithRequired(
        "user_input", PromptSectionKind::kUserInput);
    const PromptAssemblyResult result = prompt.Assembly().Assemble(
        PromptAssemblyRequest({PromptInputBinding("user_input", "   ")}));
    EXPECT_FALSE(result.Succeeded());
    EXPECT_EQ(result.status, PromptAssemblyStatus::kMissingRequiredInput);
    EXPECT_EQ(result.variable, "user_input");
}

TEST(PromptValidation, PRM_043_UnknownInputBinding) {
    Prompt prompt = BuildPromptWithRequired(
        "user_input", PromptSectionKind::kUserInput);
    const PromptAssemblyResult result = prompt.Assembly().Assemble(
        PromptAssemblyRequest({PromptInputBinding("unknown", "value")}));
    EXPECT_FALSE(result.Succeeded());
    EXPECT_EQ(result.status, PromptAssemblyStatus::kUnknownBinding);
    EXPECT_EQ(result.variable, "unknown");
}

TEST(PromptValidation, PRM_043_InvalidVariableValue) {
    Prompt prompt = BuildPromptWithRequired(
        "user_input", PromptSectionKind::kUserInput);
    const std::string invalid_value("bad\0value", 9);
    const PromptAssemblyResult result = prompt.Assembly().Assemble(
        PromptAssemblyRequest(
            {PromptInputBinding("user_input", invalid_value)}));
    EXPECT_FALSE(result.Succeeded());
    EXPECT_EQ(result.status, PromptAssemblyStatus::kInvalidValue);
    EXPECT_EQ(result.variable, "user_input");
}

TEST(PromptValidation, PRM_043_InvalidComponentSubstitution) {
    // The component references a variable that is not declared
    // by the definition (Chapter 25.2).
    Prompt prompt = Prompt(PromptDefinition(
        PromptId("bad-component"), "1.0",
        {PromptSection(
            PromptSectionKind::kUserInput,
            {PromptComponent(PromptSectionKind::kUserInput,
                             "Uses {undeclared_variable}")})},
        {PromptVariable("user_input", PromptSectionKind::kUserInput, true)}));
    const PromptAssemblyResult result = prompt.Assembly().Assemble(
        PromptAssemblyRequest({PromptInputBinding("user_input", "hello")}));
    EXPECT_FALSE(result.Succeeded());
    EXPECT_EQ(result.status, PromptAssemblyStatus::kInvalidSubstitution);
    EXPECT_EQ(result.variable, "undeclared_variable");
}

TEST(PromptValidation, PRM_043_DeterministicErrorClassification) {
    Prompt prompt = BuildPromptWithRequired(
        "memory_material", PromptSectionKind::kMemoryMaterial);
    const PromptAssemblyResult first =
        prompt.Assembly().Assemble(PromptAssemblyRequest());
    const PromptAssemblyResult second =
        prompt.Assembly().Assemble(PromptAssemblyRequest());
    EXPECT_EQ(first.status, second.status);
    EXPECT_EQ(first.variable, second.variable);
    EXPECT_EQ(first.message, second.message);
}

TEST(PromptValidation, Chapter25_DuplicateBindingNamesRejected) {
    EXPECT_THROW(
        PromptAssemblyRequest({PromptInputBinding("a", "1"),
                               PromptInputBinding("a", "2")}),
        std::invalid_argument);
}

TEST(PromptValidation, PRM_043_DefaultEnvelopeState) {
    // The deterministic envelope default is the invalid-state
    // classification; no failure path returns success.
    const PromptAssemblyResult result;
    EXPECT_EQ(result.status, PromptAssemblyStatus::kInvalidState);
    EXPECT_FALSE(result.Succeeded());
    EXPECT_FALSE(result.result.has_value());
}

}  // namespace
}  // namespace ak::prompt