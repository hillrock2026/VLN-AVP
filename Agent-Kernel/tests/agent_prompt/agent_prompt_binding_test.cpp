// ============================================================
// agent_prompt_binding_test.cpp - P1-IS007 Rev1.1 Chapter 33
// ============================================================
// AgentPromptBinding tests: the binding is Agent-owned
// production infrastructure holding a NON-OWNING reference to
// Prompt (PRM-022, AC-009); it forwards identity, definition,
// and assembly operations and returns Prompt's own result
// (Chapter 19.2).
// ============================================================

#include <agent_kernel/agent_prompt/agent_prompt_binding.hpp>
#include <agent_kernel/prompt/prompt.hpp>
#include <agent_kernel/prompt/prompt_request.hpp>

#include <gtest/gtest.h>

#include <string>
#include <type_traits>

namespace ak::agent {
namespace {

ak::prompt::Prompt MakePrompt() {
    return ak::prompt::Prompt(ak::prompt::PromptDefinition(
        ak::prompt::PromptId("binding-prompt"), "1.0",
        {ak::prompt::PromptSection(
            ak::prompt::PromptSectionKind::kUserInput,
            {ak::prompt::PromptComponent(
                ak::prompt::PromptSectionKind::kUserInput,
                "User: {user_input}")})},
        {ak::prompt::PromptVariable(
            "user_input", ak::prompt::PromptSectionKind::kUserInput,
            true)}));
}

TEST(AgentPromptBinding, PRM_022_NonOwningReference) {
    ak::prompt::Prompt prompt = MakePrompt();
    AgentPromptBinding binding(prompt);
    EXPECT_EQ(binding.Id(), ak::prompt::PromptId("binding-prompt"));
    EXPECT_EQ(binding.Definition().Version(), "1.0");
    // The binding holds a non-owning reference; it exposes no
    // Prompt() accessor and no lifecycle operations.
    static_assert(!std::is_copy_constructible_v<AgentPromptBinding>,
                  "AgentPromptBinding must be non-copyable");
    static_assert(!std::is_move_constructible_v<AgentPromptBinding>,
                  "AgentPromptBinding must be non-movable");
}

TEST(AgentPromptBinding, PRM_022_ForwardsAssemblyAndReturnsPromptResult) {
    ak::prompt::Prompt prompt = MakePrompt();
    AgentPromptBinding binding(prompt);
    const ak::prompt::PromptAssemblyRequest request(
        {ak::prompt::PromptInputBinding("user_input", "hello")});
    const ak::prompt::PromptAssemblyResult result = binding.Assemble(request);
    ASSERT_TRUE(result.Succeeded());
    ASSERT_TRUE(result.result.has_value());
    EXPECT_EQ(result.result->Id(), ak::prompt::PromptId("binding-prompt"));
    ASSERT_EQ(result.result->Components().size(), 1u);
    EXPECT_EQ(result.result->Components()[0].content, "User: hello");
}

TEST(AgentPromptBinding, PRM_022_NoIndependentLifecycleState) {
    ak::prompt::Prompt prompt = MakePrompt();
    AgentPromptBinding binding(prompt);
    // Prompt has no subsystem lifecycle state machine
    // (Chapter 16.1); the binding maintains no independent
    // lifecycle state and exposes no lifecycle operations.
    EXPECT_EQ(binding.Id(), prompt.Id());
    EXPECT_EQ(&binding.Definition(), &prompt.Definition());
}

}  // namespace
}  // namespace ak::agent