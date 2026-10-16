# ============================================================
# src/planner/CMakeLists.txt - Phase 3 Planner implementation
# boundary (P1-IS005 Rev5.1 Chapters 4.4, 16.4)
# ============================================================
# agent_kernel_planner is the Planner implementation target.
# It links ONLY the Kernel Foundation:
#   - no Agent implementation (Planner SHALL NOT include
#     ak::agent headers)
#   - no Memory/Context/Tool implementation
#   - no Runtime Adapter, Runtime Public API binding, Scheduler,
#     Executor, Workflow, or Task dependency
#
# Dependency direction: Planner -> Agent Kernel Foundation.
# ============================================================

add_library(agent_kernel_planner STATIC
    planner_state.cpp
    planning_artifact.cpp
    planner_session.cpp
    planning_engine.cpp
    planner_services.cpp
    planner_contracts.cpp
    planner_extensions.cpp
    planner.cpp
    planner_boundary_validator.cpp
)

target_include_directories(agent_kernel_planner
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_compile_features(agent_kernel_planner PUBLIC cxx_std_20)

# P1-IS005: the Planner target SHALL depend only on the Kernel
# Foundation. No Agent, Runtime, Memory, Context, or Tool target
# is linked.
target_link_libraries(agent_kernel_planner PUBLIC agent_kernel_foundation)
