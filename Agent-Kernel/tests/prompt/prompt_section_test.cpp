// ============================================================
// prompt_section_test.cpp - P1-IS007 Rev1.1 Chapter 33
// ============================================================
// Section/component tests: the eight assembly-oriented section
// categories (PRM-046), section and component accessors
// (PRM-010), immutable component/section values, malformed-
// component rejection (Chapter 25.1), and model-neutral
// component representation (PRM-016).
// ============================================================

#include <agent_kernel/prompt/prompt_section.hpp>

#include <gtest/gtest.h>

#include <stdexcept>
#include <string>
#include <vector>

namespace ak::prompt {
namespace {

TEST(PromptSection, PRM_046_AllEightCategoriesRoundTrip) {
    const std::vector<PromptSectionKind> kinds = {
        PromptSectionKind::kSystemInstruction,
        PromptSectionKind::kAgentInstruction,
        PromptSectionKind::kUserInput,
        PromptSectionKind::kMemoryMaterial,
        PromptSectionKind::kContextMaterial,
        PromptSectionKind::kPlanningMaterial,
        PromptSectionKind::kToolMaterial,
        PromptSectionKind::kAdditionalContext};
    for (const PromptSectionKind kind : kinds) {
        const PromptSection section(
            kind, {PromptComponent(kind, "content")});
        EXPECT_EQ(section.Kind(), kind);
        ASSERT_EQ(section.Components().size(), 1u);
        EXPECT_EQ(section.Components()[0].Kind(), kind);
    }
}

TEST(PromptSection, PRM_016_ComponentContentReferencesAndMetadata) {
    const PromptComponent component(
        PromptSectionKind::kUserInput,
        "User input: {user_input}",
        {"user_input"},
        {{"role", "user"}});
    EXPECT_EQ(component.Kind(), PromptSectionKind::kUserInput);
    EXPECT_EQ(component.Content(), "User input: {user_input}");
    ASSERT_EQ(component.VariableReferences().size(), 1u);
    EXPECT_EQ(component.VariableReferences()[0], "user_input");
    const auto it = component.Metadata().find("role");
    ASSERT_NE(it, component.Metadata().end());
    EXPECT_EQ(it->second, "user");
}

TEST(PromptSection, PRM_010_ComponentAndSectionImmutability) {
    const PromptComponent component(
        PromptSectionKind::kContextMaterial, "snapshot");
    const PromptComponent copy = component;
    EXPECT_EQ(copy.Content(), "snapshot");

    const PromptSection section(
        PromptSectionKind::kContextMaterial, {component});
    const PromptSection section_copy = section;
    ASSERT_EQ(section_copy.Components().size(), 1u);
    EXPECT_EQ(section_copy.Components()[0].Content(), "snapshot");
}

TEST(PromptSection, Chapter25_MalformedComponentRejected) {
    EXPECT_THROW(PromptComponent(PromptSectionKind::kUserInput, ""),
                 std::invalid_argument);
    EXPECT_THROW(PromptComponent(PromptSectionKind::kUserInput, "   "),
                 std::invalid_argument);
}

TEST(PromptSection, Chapter25_EmptySectionRejected) {
    EXPECT_THROW(
        PromptSection(PromptSectionKind::kSystemInstruction, {}),
        std::invalid_argument);
}

TEST(PromptSection, PRM_046_CategoriesAreClassificationOnly) {
    // A section category is an assembly-oriented classification
    // mechanism; it exposes no source-subsystem behavior and
    // no source-subsystem domain model (PRM-046, PRM-038).
    const PromptSection memory_section(
        PromptSectionKind::kMemoryMaterial,
        {PromptComponent(PromptSectionKind::kMemoryMaterial, "fact")});
    EXPECT_EQ(memory_section.Components().size(), 1u);
    EXPECT_EQ(memory_section.Components()[0].Content(), "fact");
}

}  // namespace
}  // namespace ak::prompt