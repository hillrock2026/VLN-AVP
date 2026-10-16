# ============================================================
# src/prompt/CMakeLists.txt - Prompt implementation boundary
# (P1-IS007 Rev1.1)
# ============================================================
# agent_kernel_prompt is the explicit Prompt implementation
# target (PRM-030). It links ONLY the Kernel Foundation:
#   - no Agent implementation
#   - no Context/Planner/Memory/Tool implementation
#   - no Runtime Adapter or Runtime Public API binding
#   - no Runtime internals
#   - no concrete Model-provider SDK
#
# P1-IS007 Rev1.1 Chapters 26, 31, 32 permitted dependency:
#   agent_kernel_prompt -> agent_kernel_foundation
#
# The Agent-facing Prompt coordination boundary lives in
# src/agent_prompt (agent_kernel_agent_prompt) and is expressed
# without a reverse Prompt -> Agent target dependency.
# ============================================================

add_library(agent_kernel_prompt STATIC
    prompt.cpp
)

target_include_directories(agent_kernel_prompt
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_compile_features(agent_kernel_prompt PUBLIC cxx_std_20)

# P1-IS007: the Prompt target SHALL depend only on the Kernel
# Foundation. No Runtime, Memory, Context, Planner, Tool, or
# Model-provider target is linked (PRM-028, PRM-029, PRM-030).
target_link_libraries(agent_kernel_prompt PUBLIC agent_kernel_foundation)