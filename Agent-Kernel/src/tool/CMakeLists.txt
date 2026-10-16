# ============================================================
# src/tool/CMakeLists.txt - Phase 4 Tool implementation
# boundary (P1-IS006 Rev2)
# ============================================================
# agent_kernel_tool is the explicit Tool implementation target
# (TOL-009). It links ONLY the Kernel Foundation:
#   - no Agent implementation
#   - no Context/Planner/Memory implementation
#   - no Runtime Adapter or Runtime Public API binding
#   - no Runtime internals
#
# P1-IS006 Rev2 Chapter 6 permitted dependencies (TOL-102):
#   agent_kernel_tool -> agent_kernel_foundation
#
# The Agent-facing Tool coordination boundary lives in
# src/agent_tool (agent_kernel_agent_tool) and is expressed
# without a reverse Tool -> Agent target dependency.
# ============================================================

add_library(agent_kernel_tool STATIC
    tool.cpp
)

target_include_directories(agent_kernel_tool
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_compile_features(agent_kernel_tool PUBLIC cxx_std_20)

# P1-IS006: the Tool target SHALL depend only on the Kernel
# Foundation. No Runtime, Scheduler, Executor, Capability
# Resolver, or Event Bus target is linked.
target_link_libraries(agent_kernel_tool PUBLIC agent_kernel_foundation)