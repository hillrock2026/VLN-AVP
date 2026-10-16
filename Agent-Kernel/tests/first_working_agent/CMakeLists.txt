# ============================================================
# tests/first_working_agent/CMakeLists.txt - First Working
# Agent Sprint tests (TASK 6 Rev2 §27-§28)
# ============================================================
# One CTest executable (model_action_test.cpp = FWA-005,
# first_working_agent_integration_test.cpp = FWA-001..004 +
# max-cycles + determinism) plus one boundary-check test.
# ============================================================

find_package(GTest REQUIRED)

add_executable(first_working_agent_integration_test
    model_action_test.cpp
    first_working_agent_integration_test.cpp
)

target_include_directories(first_working_agent_integration_test
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
)

target_link_libraries(first_working_agent_integration_test
    PRIVATE
        agent_kernel_first_working_agent
        agent_kernel_agent
        agent_kernel_agent_planner
        agent_kernel_agent_tool
        agent_kernel_agent_prompt
        agent_kernel_tool
        agent_kernel_context
        agent_kernel_memory
        agent_kernel_foundation
        GTest::gtest_main
)

target_compile_features(first_working_agent_integration_test PRIVATE cxx_std_20)

add_test(NAME FirstWorkingAgentTest COMMAND first_working_agent_integration_test)

# Static boundary verification (TASK 6 Rev2 §27): no Runtime
# include/link, no test header in production, model_action.hpp
# include scope, exact link set.
add_test(NAME FirstWorkingAgentBoundaryCheck
    COMMAND ${CMAKE_COMMAND}
        -DFWA_COMPOSITION_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/fwa
        -DFWA_AGENT_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/agent
        -DFWA_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../src/agent/composition
        -DFWA_TEST_DIR=${CMAKE_CURRENT_SOURCE_DIR}
        -DFWA_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_first_working_agent,LINK_LIBRARIES>
        -DFWA_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_first_working_agent,INTERFACE_LINK_LIBRARIES>
        -P ${CMAKE_CURRENT_SOURCE_DIR}/check_first_working_agent_boundaries.cmake
)
