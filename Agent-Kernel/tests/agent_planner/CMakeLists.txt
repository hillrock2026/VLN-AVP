# ============================================================
# tests/agent_planner/CMakeLists.txt - P1-IS005 Agent-owned
# production composition tests
# ============================================================
# agent_planner_test: host/binding behavior, refusal gate,
# production composition.
# planner_integration_test: REAL Agent -> Host -> Binding ->
# Planner end-to-end, plus unchanged Phase 1
# IPlannerContract/AgentCoordinationService verification
# (P1-IS005 Rev5.1 Chapter 20.5).
# ============================================================

find_package(GTest REQUIRED)

add_executable(agent_planner_test
    agent_planner_host_test.cpp
    agent_planner_binding_test.cpp
)

target_include_directories(agent_planner_test
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
)

target_link_libraries(agent_planner_test
    PRIVATE
        agent_kernel_agent_planner
        agent_kernel_planner
        agent_kernel_foundation
        GTest::gtest_main
)

target_compile_features(agent_planner_test PRIVATE cxx_std_20)

add_test(NAME AgentPlannerTest COMMAND agent_planner_test)

add_executable(planner_integration_test
    integration_test.cpp
)

target_include_directories(planner_integration_test
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
)

target_link_libraries(planner_integration_test
    PRIVATE
        agent_kernel_agent_planner
        agent_kernel_planner
        agent_kernel_agent
        agent_kernel_foundation
        GTest::gtest_main
)

target_compile_features(planner_integration_test PRIVATE cxx_std_20)

add_test(NAME PlannerIntegrationTest COMMAND planner_integration_test)

# Agent-side host boundary check: agent_kernel_agent_planner
# links ONLY agent_kernel_planner + agent_kernel_foundation and
# contains no Runtime dependency (P1-IS005 Chapter 20.7 item 4).
add_test(NAME AgentPlannerBoundaryCheck
    COMMAND ${CMAKE_COMMAND}
        -DAGENT_PLANNER_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/agent_planner
        -DAGENT_PLANNER_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../src/agent_planner
        -DAGENT_PLANNER_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_agent_planner,LINK_LIBRARIES>
        -DAGENT_PLANNER_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_agent_planner,INTERFACE_LINK_LIBRARIES>
        -P ${CMAKE_CURRENT_SOURCE_DIR}/check_agent_planner_boundaries.cmake
)
