# ============================================================
# src/memory/CMakeLists.txt - Phase 2 Memory implementation
# boundary (P1-IS003)
# ============================================================
# agent_kernel_memory is the explicit Memory implementation
# target. It links ONLY the Kernel Foundation:
#   - no Agent implementation
#   - no Context/Planner/Tool implementation
#   - no Runtime Adapter or Runtime Public API binding
#   - no Runtime internals
#
# P1-IS003 Chapter 6 permitted dependencies:
#   Memory -> Kernel Foundation
#
# The Agent-facing Memory coordination contract lives inside
# this boundary (ak::memory) and is expressed without a reverse
# Memory -> Agent target dependency.
# ============================================================

add_library(agent_kernel_memory STATIC
    memory.cpp
    memory_lifecycle.cpp
    memory_operational_state.cpp
    memory_state.cpp
    memory_objects.cpp
    memory_provider.cpp
    memory_services.cpp
    memory_agent_contract.cpp
    memory_extensions.cpp
    memory_boundary_validator.cpp
)

target_include_directories(agent_kernel_memory
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_compile_features(agent_kernel_memory PUBLIC cxx_std_20)

# P1-IS003: the Memory target SHALL depend only on the Kernel
# Foundation. No Runtime, Agent, Context, Planner, or Tool
# target is linked.
target_link_libraries(agent_kernel_memory PUBLIC agent_kernel_foundation)