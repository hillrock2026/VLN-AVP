# ============================================================
# tests/agent/CMakeLists.txt - P1-IS002 Agent tests
# ============================================================
# Behavioral and structural conformance tests for the Phase 1
# Agent implementation, plus a static dependency/Runtime-
# boundary check.
# ============================================================

find_package(GTest REQUIRED)

add_executable(agent_test
    agent_identity_test.cpp
    agent_lifecycle_test.cpp
    agent_state_test.cpp
    execution_objective_test.cpp
    coordination_test.cpp
    execution_composition_test.cpp
    runtime_isolation_test.cpp
    extension_boundary_test.cpp
    ownership_dependency_test.cpp
    boundary_validator_test.cpp
)

target_include_directories(agent_test
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
)

target_link_libraries(agent_test
    PRIVATE
        agent_kernel_agent
        agent_kernel_foundation
        GTest::gtest_main
)

target_compile_features(agent_test PRIVATE cxx_std_20)

add_test(NAME AgentTest COMMAND agent_test)

# P1-IS002 Chapter 15.7 / Chapter 26.6 static boundary check:
# - Agent headers/sources include no Runtime internals and no
#   Memory/Context/Planner/Tool internals.
# - The Agent build target links only the Kernel Foundation.
add_test(NAME AgentBoundaryCheck
    COMMAND ${CMAKE_COMMAND}
        -DAGENT_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/agent
        -DAGENT_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../src/agent
        -DAGENT_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_agent,LINK_LIBRARIES>
        -DAGENT_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_agent,INTERFACE_LINK_LIBRARIES>
        -P ${CMAKE_CURRENT_SOURCE_DIR}/check_agent_boundaries.cmake
)
