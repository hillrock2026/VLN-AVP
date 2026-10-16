# ============================================================
# src/context/CMakeLists.txt - Phase 2 Context implementation
# boundary (P1-IS004)
# ============================================================
# agent_kernel_context is the explicit Context implementation
# target. It links ONLY the Kernel Foundation:
#   - no Agent implementation
#   - no Memory/Planner/Tool implementation
#   - no Runtime Adapter or Runtime Public API binding
#   - no Runtime internals
#
# P1-IS004 Chapter 17 permitted dependencies:
#   Context -> Kernel Foundation
#
# The Agent-facing Context coordination contract lives inside
# this boundary (ak::context) and is expressed without a reverse
# Context -> Agent target dependency.
# ============================================================

add_library(agent_kernel_context STATIC
    context.cpp
    context_lifecycle.cpp
    context_operational_state.cpp
    context_state.cpp
    context_objects.cpp
    context_services.cpp
    context_agent_contract.cpp
    context_extensions.cpp
    context_boundary_validator.cpp
)

target_include_directories(agent_kernel_context
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_compile_features(agent_kernel_context PUBLIC cxx_std_20)

# P1-IS004: the Context target SHALL depend only on the Kernel
# Foundation. No Runtime, Agent, Memory, Planner, or Tool target
# is linked.
target_link_libraries(agent_kernel_context PUBLIC agent_kernel_foundation)
