# ============================================================
# tests/planner/CMakeLists.txt - P1-IS005 Planner tests
# ============================================================
# Behavioral and structural conformance tests for the Phase 3
# Planner implementation, plus a static dependency/Runtime-
# boundary check (P1-IS005 Rev5.1 Chapters 19-20).
# ============================================================

find_package(GTest REQUIRED)

add_executable(planner_test
    planner_identity_test.cpp
    planner_lifecycle_test.cpp
    planner_state_test.cpp
    planner_exchange_test.cpp
    planner_exactly_once_test.cpp
    planner_artifact_test.cpp
    planner_session_test.cpp
    planner_termination_test.cpp
    planner_extension_test.cpp
    planner_runtime_isolation_test.cpp
    planner_boundary_validator_test.cpp
    planner_foundation_reuse_test.cpp
)

target_include_directories(planner_test
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
)

target_link_libraries(planner_test
    PRIVATE
        agent_kernel_planner
        agent_kernel_foundation
        GTest::gtest_main
)

target_compile_features(planner_test PRIVATE cxx_std_20)

add_test(NAME PlannerTest COMMAND planner_test)

# P1-IS005 Chapters 19.2 / 20.7 static boundary check:
# - Planner headers/sources include no Agent/Memory/Context/Tool
#   internals and no Runtime internals.
# - The Planner build target links only the Kernel Foundation.
add_test(NAME PlannerBoundaryCheck
    COMMAND ${CMAKE_COMMAND}
        -DPLANNER_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/planner
        -DPLANNER_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../src/planner
        -DPLANNER_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_planner,LINK_LIBRARIES>
        -DPLANNER_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_planner,INTERFACE_LINK_LIBRARIES>
        -P ${CMAKE_CURRENT_SOURCE_DIR}/check_planner_boundaries.cmake
)
