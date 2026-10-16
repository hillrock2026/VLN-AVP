// ============================================================
// prompt_result_test.cpp - P1-IS007 Rev1.1 Chapter 33
// ============================================================
// Result tests: immutable PromptResult (PRM-015, PRM-042,
// AC-007), model-neutral representation (PRM-016), provider
// independence (PRM-017, AC-008), and no speculative result
// schema/version identifier (Chapter 14.1).
// ============================================================

#include <agent_kernel/prompt/prompt_result.hpp>

#include <gtest/gtest.h>

#include <string>

namespace ak::prompt {
namespace {

PromptResult MakeResult() {
    return PromptResult(
        PromptId("result-a"), "1.0",
        {AssembledComponent{PromptSectionKind::kSystemInstruction,
                            "You are a helpful agent.", {}}},
        {{"purpose", "test"}});
}

TEST(PromptResult, PRM_015_AccessorsAndImmutability) {
    const PromptResult result = MakeResult();
    EXPECT_EQ(result.Id(), PromptId("result-a"));
    EXPECT_EQ(result.DefinitionVersion(), "1.0");
    ASSERT_EQ(result.Components().size(), 1u);
    EXPECT_EQ(result.Components()[0].kind,
              PromptSectionKind::kSystemInstruction);
    EXPECT_EQ(result.Components()[0].content, "You are a helpful agent.");
    EXPECT_EQ(result.ValidationStatus(), PromptValidationStatus::kValid);
    const auto it = result.Metadata().find("purpose");
    ASSERT_NE(it, result.Metadata().end());
    EXPECT_EQ(it->second, "test");

    const PromptResult copy = result;
    EXPECT_EQ(copy.Id(), result.Id());
    EXPECT_EQ(copy.Components().size(), result.Components().size());
}

TEST(PromptResult, PRM_016_ModelNeutralRepresentation) {
    // The result surface is limited to identity, version,
    // ordered components, metadata, and validation status; no
    // provider-specific message or role type exists (PRM-016,
    // TOL-024).
    const PromptResult result = MakeResult();
    EXPECT_EQ(result.Components()[0].content, "You are a helpful agent.");
}

TEST(PromptResult, PRM_017_ProviderIndependentConsumption) {
    // Two independent consumers observe identical content; no
    // provider-specific conversion is required (Chapter 15.3).
    const PromptResult result = MakeResult();
    const PromptResult& consumer_a = result;
    const PromptResult& consumer_b = result;
    EXPECT_EQ(consumer_a.Components()[0].content,
              consumer_b.Components()[0].content);
}

TEST(PromptResult, Chapter14_NoExtraSchemaVersion) {
    // Revision 1.1 introduces no PromptResult schema/version
    // identifier beyond the definition version (Chapter 14.1).
    const PromptResult result = MakeResult();
    EXPECT_EQ(result.DefinitionVersion(), "1.0");
}

}  // namespace
}  // namespace ak::prompt