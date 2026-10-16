# ============================================================
# src/agent_planner/CMakeLists.txt - Phase 3 Agent-owned
# Planner production composition (P1-IS005 Rev5.1 Chapters
# 15-16, 16.4)
# ============================================================
# agent_kernel_agent_planner is the Agent-owned production
# invocation surface (AgentPlannerBinding, AgentPlannerHost).
# It links ONLY:
#   - agent_kernel_planner (direction Agent -> Planner)
#   - agent_kernel_foundation
#
# It SHALL NOT be linked into agent_kernel_planner (no reverse
# dependency), and it carries no Runtime dependency.
# ============================================================

add_library(agent_kernel_agent_planner STATIC
    agent_planner_binding.cpp
    agent_planner_host.cpp
)

target_include_directories(agent_kernel_agent_planner
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_compile_features(agent_kernel_agent_planner PUBLIC cxx_std_20)

# P1-IS005: Agent-owned infrastructure depends on the Planner
# target and the Kernel Foundation ONLY.
target_link_libraries(agent_kernel_agent_planner
    PUBLIC
        agent_kernel_planner
        agent_kernel_foundation
)
