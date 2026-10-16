// ============================================================
// agent_prompt_host_test.cpp - P1-IS007 Rev1.1 Chapter 33
// ============================================================
// AgentPromptHost tests: the host is the single production
// composition root (PRM-023, AC-009); it owns the Prompt root
// and the binding view; AgentPromptHost is NOT a lifecycle
// authority (PRM-048, TOL-033); the host exposes no public
// Prompt() accessor (Chapter 19.3).
// ============================================================

#include <agent_kernel/agent_prompt/agent_prompt_host.hpp>
#include <agent_kernel/prompt/prompt.hpp>
#include <agent_kernel/prompt/prompt_request.hpp>

#include <gtest/gtest.h>

#include <string>
#include <type_traits>

namespace ak::agent {
namespace {

ak::prompt::PromptDefinition MakeDefinition() {
    return ak::prompt::PromptDefinition(
        ak::prompt::PromptId("host-prompt"), "1.0",
        {ak::prompt::PromptSection(
            ak::prompt::PromptSectionKind::kSystemInstruction,
            {ak::prompt::PromptComponent(
                ak::prompt::PromptSectionKind::kSystemInstruction,
                "You are a helpful agent.")})},
        {});
}

TEST(AgentPromptHost, PRM_023_OwnsPromptAndBinding) {
    AgentPromptHost host(MakeDefinition());
    const AgentPromptBinding& binding = host.Binding();
    EXPECT_EQ(binding.Id(), ak::prompt::PromptId("host-prompt"));
    EXPECT_EQ(binding.Definition().Version(), "1.0");
}

TEST(AgentPromptHost, PRM_048_NotLifecycleAuthority) {
    // Constructing the Prompt root as an ordinary owned object
    // is ordinary object construction, not subsystem lifecycle
    // authority (Chapters 16.1, 19.3). The host exposes only
    // the binding; no lifecycle operations exist.
    AgentPromptHost host(MakeDefinition());
    EXPECT_EQ(host.Binding().Id(), ak::prompt::PromptId("host-prompt"));
}

TEST(AgentPromptHost, AC_009_AgentCoordinatesThroughBinding) {
    AgentPromptHost host(MakeDefinition());
    AgentPromptBinding& binding = host.Binding();
    const ak::prompt::PromptAssemblyRequest request;
    const ak::prompt::PromptAssemblyResult result = binding.Assemble(request);
    ASSERT_TRUE(result.Succeeded());
    ASSERT_EQ(result.result->Components().size(), 1u);
    EXPECT_EQ(result.result->Components()[0].content,
              "You are a helpful agent.");
}

TEST(AgentPromptHost, Chapter19_NonCopyableCompositionRoot) {
    static_assert(!std::is_copy_constructible_v<AgentPromptHost>,
                  "AgentPromptHost owns Prompt and the binding");
    static_assert(!std::is_copy_assignable_v<AgentPromptHost>);
}

}  // namespace
}  // namespace ak::agent