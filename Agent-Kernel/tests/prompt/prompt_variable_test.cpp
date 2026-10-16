// ============================================================
// prompt_variable_test.cpp - P1-IS007 Rev1.1 Chapter 33
// ============================================================
// Variable declaration tests: name/category/required accessors
// (PRM-011), immutability of variable definitions (Chapter 17),
// and malformed-name rejection (Chapter 25.1).
// ============================================================

#include <agent_kernel/prompt/prompt_variable.hpp>

#include <gtest/gtest.h>

#include <stdexcept>
#include <string>

namespace ak::prompt {
namespace {

TEST(PromptVariable, PRM_011_NameCategoryRequiredAccessors) {
    const PromptVariable variable(
        "user_input", PromptSectionKind::kUserInput, true);
    EXPECT_EQ(variable.Name(), "user_input");
    EXPECT_EQ(variable.Category(), PromptSectionKind::kUserInput);
    EXPECT_TRUE(variable.Required());

    const PromptVariable optional(
        "context_snapshot", PromptSectionKind::kContextMaterial, false);
    EXPECT_FALSE(optional.Required());
    EXPECT_EQ(optional.Category(), PromptSectionKind::kContextMaterial);
}

TEST(PromptVariable, PRM_011_Immutability) {
    const PromptVariable variable(
        "memory_material", PromptSectionKind::kMemoryMaterial, true);
    const PromptVariable copy = variable;
    EXPECT_EQ(copy.Name(), variable.Name());
    EXPECT_EQ(copy.Category(), variable.Category());
    EXPECT_EQ(copy.Required(), variable.Required());
}

TEST(PromptVariable, Chapter25_EmptyNameRejected) {
    EXPECT_THROW(PromptVariable("", PromptSectionKind::kUserInput, true),
                 std::invalid_argument);
    EXPECT_THROW(PromptVariable("   ", PromptSectionKind::kUserInput, true),
                 std::invalid_argument);
}

}  // namespace
}  // namespace ak::prompt