# ============================================================
# src/agent_tool/CMakeLists.txt - Phase 4 Agent-owned Tool
# coordination boundary (P1-IS006 Rev2)
# ============================================================
# agent_kernel_agent_tool is the Agent-owned production
# coordination surface (AgentToolBinding, AgentToolHost)
# (TOL-010). It links ONLY:
#   - agent_kernel_tool (direction Agent -> Tool)
#   - agent_kernel_foundation
#
# P1-IS006 Rev2 Chapter 6 permitted dependencies (TOL-102):
#   agent_kernel_agent_tool -> agent_kernel_tool,
#                              agent_kernel_foundation
#
# It SHALL NOT be linked into agent_kernel_tool (no reverse
# dependency), and it carries no Runtime dependency.
# ============================================================

add_library(agent_kernel_agent_tool STATIC
    agent_tool_binding.cpp
    agent_tool_host.cpp
)

target_include_directories(agent_kernel_agent_tool
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_compile_features(agent_kernel_agent_tool PUBLIC cxx_std_20)

# P1-IS006: Agent-owned Tool coordination depends on the Tool
# target and the Kernel Foundation ONLY (TOL-102).
target_link_libraries(agent_kernel_agent_tool
    PUBLIC
        agent_kernel_tool
        agent_kernel_foundation
)