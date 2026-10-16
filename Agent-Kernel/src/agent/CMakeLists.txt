# ============================================================
# src/agent/CMakeLists.txt - Phase 1 Agent implementation
# boundary (P1-IS002)
# ============================================================
# agent_kernel_agent is the explicit Agent implementation
# target. It links ONLY the Kernel Foundation:
#   - no Memory/Context/Planner/Tool implementation
#   - no Execution Composition target (Agent-coordinated
#     representation lives inside this boundary)
#   - no Runtime Adapter
#   - no Runtime internals or Runtime Public API binding
#
# P1-IS002 Chapter 19.1 permitted Phase 1 dependencies:
#   Agent -> Kernel Foundation
#   Agent -> Memory/Context/Planner/Tool contracts (header-only
#            contract surfaces within this boundary)
#   Agent -> Agent-owned Runtime interaction port/contract
#
# Phase 5 concrete Agent-Runtime integration SHALL NOT be
# linked here. Compilation into a shared binary must not erase
# this logical boundary.
# ============================================================

add_library(agent_kernel_agent STATIC
    agent.cpp
    agent_state.cpp
    agent_coordination_service.cpp
    execution_composition.cpp
    agent_extension_boundary.cpp
    agent_boundary_validator.cpp
)

target_include_directories(agent_kernel_agent
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_compile_features(agent_kernel_agent PUBLIC cxx_std_20)

# P1-IS002: the Agent target SHALL depend only on the Kernel
# Foundation. No Runtime target is linked.
target_link_libraries(agent_kernel_agent PUBLIC agent_kernel_foundation)
