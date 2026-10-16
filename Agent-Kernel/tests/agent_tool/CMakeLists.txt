# ============================================================
# tests/agent_tool/CMakeLists.txt - P1-IS006 Rev2 Agent-Tool
# boundary tests
# ============================================================
# agent_kernel_agent_tool_tests: AgentToolBinding behavior and
# REAL Agent -> AgentToolHost -> AgentToolBinding -> Tool
# end-to-end composition, plus unchanged Phase 1
# IToolContract/AgentCoordinationService verification
# (P1-IS006 Rev2 Chapters 24-25, 33.9-33.10, TOL-012,
# TOL-086).
# ============================================================

find_package(GTest REQUIRED)

add_executable(agent_kernel_agent_tool_tests
    agent_tool_binding_test.cpp
    agent_tool_integration_test.cpp
)

target_include_directories(agent_kernel_agent_tool_tests
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../tool>
)

target_link_libraries(agent_kernel_agent_tool_tests
    PRIVATE
        agent_kernel_agent_tool
        agent_kernel_tool
        agent_kernel_agent
        agent_kernel_foundation
        GTest::gtest_main
)

target_compile_features(agent_kernel_agent_tool_tests PRIVATE cxx_std_20)

target_compile_definitions(agent_kernel_agent_tool_tests
    PRIVATE AK_INCLUDE_ROOT="${CMAKE_CURRENT_SOURCE_DIR}/../../include")

add_test(NAME AgentToolTest COMMAND agent_kernel_agent_tool_tests)

# Agent-side host boundary check: agent_kernel_agent_tool links
# ONLY agent_kernel_tool + agent_kernel_foundation and contains
# no Runtime dependency (P1-IS006 Rev2 Chapter 6, TOL-102).
add_test(NAME AgentToolBoundaryCheck
    COMMAND ${CMAKE_COMMAND}
        -DAGENT_TOOL_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/agent_tool
        -DAGENT_TOOL_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../src/agent_tool
        -DAGENT_TOOL_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_agent_tool,LINK_LIBRARIES>
        -DAGENT_TOOL_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_agent_tool,INTERFACE_LINK_LIBRARIES>
        -P ${CMAKE_CURRENT_SOURCE_DIR}/check_agent_tool_boundaries.cmake
)