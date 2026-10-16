// ============================================================
// prompt_definition_test.cpp - P1-IS007 Rev1.1 Chapter 33
// ============================================================
// Definition tests: immutable assembly configuration (PRM-009,
// AC-003), structural validation (Chapter 25.1), metadata
// preservation, and stable identity (AC-002).
// ============================================================

#include <agent_kernel/prompt/prompt_definition.hpp>

#include <gtest/gtest.h>

#include <stdexcept>
#include <string>
#include <vector>

namespace ak::prompt {
namespace {

PromptDefinition MakeValidDefinition() {
    return PromptDefinition(
        PromptId("definition-a"),
        "1.0",
        {PromptSection(
            PromptSectionKind::kSystemInstruction,
            {PromptComponent(PromptSectionKind::kSystemInstruction,
                             "You are a helpful agent.")})},
        {PromptVariable("user_input", PromptSectionKind::kUserInput, true)});
}

TEST(PromptDefinition, PRM_009_AccessorsAndImmutability) {
    const PromptDefinition definition = MakeValidDefinition();
    EXPECT_EQ(definition.Id(), PromptId("definition-a"));
    EXPECT_EQ(definition.Version(), "1.0");
    ASSERT_EQ(definition.Sections().size(), 1u);
    EXPECT_EQ(definition.Sections()[0].Kind(),
              PromptSectionKind::kSystemInstruction);
    ASSERT_EQ(definition.Variables().size(), 1u);
    EXPECT_EQ(definition.Variables()[0].Name(), "user_input");

    const PromptDefinition copy = definition;
    EXPECT_EQ(copy.Id(), definition.Id());
    EXPECT_EQ(copy.Version(), definition.Version());
    EXPECT_EQ(copy.Sections().size(), definition.Sections().size());
}

TEST(PromptDefinition, PRM_009_MetadataPreserved) {
    const PromptDefinition definition = PromptDefinition(
        PromptId("definition-b"), "2.0",
        {PromptSection(
            PromptSectionKind::kUserInput,
            {PromptComponent(PromptSectionKind::kUserInput, "hi")})},
        {}, {{"purpose", "test"}});
    const auto it = definition.Metadata().find("purpose");
    ASSERT_NE(it, definition.Metadata().end());
    EXPECT_EQ(it->second, "test");
}

TEST(PromptDefinition, Chapter25_EmptyVersionRejected) {
    EXPECT_THROW(
        PromptDefinition(
            PromptId("x"), "",
            {PromptSection(
                PromptSectionKind::kUserInput,
                {PromptComponent(PromptSectionKind::kUserInput, "c")})},
            {}),
        std::invalid_argument);
}

TEST(PromptDefinition, Chapter25_EmptySectionsRejected) {
    EXPECT_THROW(PromptDefinition(PromptId("x"), "1.0", {}, {}),
                 std::invalid_argument);
}

TEST(PromptDefinition, Chapter25_DuplicateVariableNamesRejected) {
    EXPECT_THROW(
        PromptDefinition(
            PromptId("x"), "1.0",
            {PromptSection(
                PromptSectionKind::kUserInput,
                {PromptComponent(PromptSectionKind::kUserInput, "c")})},
            {PromptVariable("dup", PromptSectionKind::kUserInput, true),
             PromptVariable("dup", PromptSectionKind::kMemoryMaterial, false)}),
        std::invalid_argument);
}

}  // namespace
}  // namespace ak::prompt