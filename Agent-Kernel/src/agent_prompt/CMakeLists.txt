# ============================================================
# src/agent_prompt/CMakeLists.txt - Agent-owned Prompt
# coordination boundary (P1-IS007 Rev1.1)
# ============================================================
# agent_kernel_agent_prompt is the Agent-owned production
# coordination surface (AgentPromptBinding, AgentPromptHost)
# (PRM-022, PRM-023, PRM-039). It links ONLY:
#   - agent_kernel_prompt (direction Agent -> Prompt)
#   - agent_kernel_foundation
#
# P1-IS007 Rev1.1 Chapters 26, 31 permitted dependencies:
#   agent_kernel_agent_prompt -> agent_kernel_prompt,
#                                agent_kernel_foundation
#
# It SHALL NOT be linked into agent_kernel_prompt (no reverse
# dependency) and carries no Runtime dependency.
# ============================================================

add_library(agent_kernel_agent_prompt STATIC
    agent_prompt_binding.cpp
    agent_prompt_host.cpp
)

target_include_directories(agent_kernel_agent_prompt
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_compile_features(agent_kernel_agent_prompt PUBLIC cxx_std_20)

# P1-IS007: Agent-owned Prompt coordination depends on the
# Prompt target and the Kernel Foundation ONLY (PRM-030).
target_link_libraries(agent_kernel_agent_prompt
    PUBLIC
        agent_kernel_prompt
        agent_kernel_foundation
)