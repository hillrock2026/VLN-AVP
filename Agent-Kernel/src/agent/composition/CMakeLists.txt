# ============================================================
# src/agent/composition/CMakeLists.txt - First Working Agent
# Sprint, TASK 6 Rev2 §27
# ============================================================
# agent_kernel_first_working_agent is the single new production
# target: the Agent-owned composition root. It links ONLY
# Agent-owned infrastructure and existing subsystem targets in
# the direction Agent -> subsystem (TASK 6 Rev2 §27):
#   agent_kernel_agent
#   agent_kernel_agent_planner (+ planner transitively)
#   agent_kernel_agent_tool (+ tool transitively)
#   agent_kernel_agent_prompt (+ prompt transitively)
#   agent_kernel_tool       (composition constructs Tool root
#                            directly - governance §9A)
#   agent_kernel_context
#   agent_kernel_memory
#   agent_kernel_foundation
#
# NO Runtime link (INV-021); no subsystem -> Agent edge; no
# cycle. No test header is included by or linked into this
# production target (OBS-03).
# ============================================================

add_library(agent_kernel_first_working_agent STATIC
    first_working_agent_composition.cpp
)

target_include_directories(agent_kernel_first_working_agent
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_compile_features(agent_kernel_first_working_agent PUBLIC cxx_std_20)

target_link_libraries(agent_kernel_first_working_agent
    PUBLIC
        agent_kernel_agent
        agent_kernel_agent_planner
        agent_kernel_agent_tool
        agent_kernel_agent_prompt
        agent_kernel_tool
        agent_kernel_context
        agent_kernel_memory
        agent_kernel_foundation
)
