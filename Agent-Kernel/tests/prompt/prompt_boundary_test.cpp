// ============================================================
// prompt_boundary_test.cpp - P1-IS007 Rev1.1 Chapters 28, 36
// ============================================================
// Boundary tests: Prompt consumes Memory/Context/Planner/Tool
// information only as values supplied through the
// PromptAssemblyRequest (PRM-036, PRM-037, AC-028); Prompt
// defines no mirror domain models (PRM-038, AC-029); assembly
// is side-effect free with respect to external values
// (AC-017); and the Prompt surface exposes no Runtime, Model,
// or lifecycle authority (AC-010..AC-020).
//
// Static dependency/link boundaries are verified separately by
// tests/prompt/check_prompt_boundaries.cmake (Chapter 36).
// ============================================================

#include <agent_kernel/prompt/prompt.hpp>
#include <agent_kernel/prompt/prompt_request.hpp>
#include <agent_kernel/prompt/prompt_result.hpp>

#include <gtest/gtest.h>

#include <string>

namespace ak::prompt {
namespace {

// Materials from all four source boundaries are consumed ONLY
// as values carried by the request (Chapters 20-23, PRM-037).
Prompt BuildAllMaterialsPrompt() {
    return Prompt(PromptDefinition(
        PromptId("boundary-prompt"), "1.0",
        {PromptSection(
             PromptSectionKind::kMemoryMaterial,
             {PromptComponent(PromptSectionKind::kMemoryMaterial,
                              "Memory: {memory_material}")}),
         PromptSection(
             PromptSectionKind::kContextMaterial,
             {PromptComponent(PromptSectionKind::kContextMaterial,
                              "Context: {context_snapshot}")}),
         PromptSection(
             PromptSectionKind::kPlanningMaterial,
             {PromptComponent(PromptSectionKind::kPlanningMaterial,
                              "Plan: {plan_summary}")}),
         PromptSection(
             PromptSectionKind::kToolMaterial,
             {PromptComponent(PromptSectionKind::kToolMaterial,
                              "Tools: {tool_capabilities}")})},
        {PromptVariable("memory_material",
                        PromptSectionKind::kMemoryMaterial, true),
         PromptVariable("context_snapshot",
                        PromptSectionKind::kContextMaterial, true),
         PromptVariable("plan_summary",
                        PromptSectionKind::kPlanningMaterial, true),
         PromptVariable("tool_capabilities",
                        PromptSectionKind::kToolMaterial, true)}));
}

PromptAssemblyRequest MakeAllMaterialsRequest(const std::string& context) {
    return PromptAssemblyRequest(
        {PromptInputBinding("memory_material", "retained fact"),
         PromptInputBinding("context_snapshot", context),
         PromptInputBinding("plan_summary", "step 1; step 2"),
         PromptInputBinding("tool_capabilities", "capability-a")});
}

TEST(PromptBoundary, PRM_036_MaterialsArriveOnlyThroughRequest) {
    Prompt prompt = BuildAllMaterialsPrompt();
    const PromptAssemblyResult result =
        prompt.Assembly().Assemble(MakeAllMaterialsRequest("working state"));
    ASSERT_TRUE(result.Succeeded());
    ASSERT_EQ(result.result->Components().size(), 4u);
    EXPECT_EQ(result.result->Components()[0].content, "Memory: retained fact");
    EXPECT_EQ(result.result->Components()[1].content,
              "Context: working state");
    EXPECT_EQ(result.result->Components()[2].content, "Plan: step 1; step 2");
    EXPECT_EQ(result.result->Components()[3].content,
              "Tools: capability-a");
}

TEST(PromptBoundary, AC_017_AssemblyDoesNotMutateExternalValues) {
    std::string external = "working state";
    Prompt prompt = BuildAllMaterialsPrompt();
    const PromptAssemblyResult result = prompt.Assembly().Assemble(
        MakeAllMaterialsRequest(external));
    ASSERT_TRUE(result.Succeeded());
    EXPECT_EQ(external, "working state");  // unchanged (AC-017)
}

TEST(PromptBoundary, PRM_038_NoMirrorDomainModelsOnSurface) {
    // The static boundary check (tests/prompt/check_prompt_
    // boundaries.cmake) verifies that no PromptMemory /
    // PromptContext / PromptPlanner / PromptTool identifiers
    // exist anywhere in the Prompt boundary. This test verifies
    // the material values remain plain values, not mirror
    // objects (PRM-038, AC-029).
    Prompt prompt = BuildAllMaterialsPrompt();
    const PromptAssemblyResult result =
        prompt.Assembly().Assemble(MakeAllMaterialsRequest("state"));
    ASSERT_TRUE(result.Succeeded());
    EXPECT_EQ(result.result->Components()[0].content, "Memory: retained fact");
}

TEST(PromptBoundary, PRM_008_NoRuntimeDependency) {
    // The Prompt boundary links only the Kernel Foundation
    // (CMake boundary check). Behaviorally, assembly is
    // independent of any execution infrastructure.
    Prompt prompt = BuildAllMaterialsPrompt();
    EXPECT_TRUE(
        prompt.Assembly().Assemble(MakeAllMaterialsRequest("state"))
            .Succeeded());
}

TEST(PromptBoundary, PRM_018_NoLifecycleAuthority) {
    // Prompt lifecycle is object lifetime (Chapter 16.1): the
    // root exposes identity, definition, and services only; no
    // lifecycle operations exist on the surface. Construction
    // and destruction of the root are ordinary object
    // operations (PRM-048).
    Prompt prompt = BuildAllMaterialsPrompt();
    EXPECT_EQ(prompt.Id(), PromptId("boundary-prompt"));
    EXPECT_EQ(prompt.Definition().Version(), "1.0");
}

}  // namespace
}  // namespace ak::prompt