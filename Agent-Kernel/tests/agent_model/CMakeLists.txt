# ============================================================
# tests/agent_model/CMakeLists.txt - P1-IS008 Rev1.0
# Agent-Model tests
# ============================================================
# Binding, host, and Agent-Model integration tests (Chapters
# 15, 19.3) plus a static dependency/Runtime-boundary check.
# The integration tests exercise the real ak::agent::Agent,
# the Agent-owned Model boundary, and the deterministic test
# double (tests/model/deterministic_model.hpp).
# ============================================================

find_package(GTest REQUIRED)

add_executable(agent_kernel_agent_model_tests
    agent_model_binding_test.cpp
    agent_model_host_test.cpp
    agent_model_integration_test.cpp
)

target_include_directories(agent_kernel_agent_model_tests
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        ${CMAKE_CURRENT_SOURCE_DIR}/../model
)

target_link_libraries(agent_kernel_agent_model_tests
    PRIVATE
        agent_kernel_agent_model
        agent_kernel_model
        agent_kernel_agent
        agent_kernel_agent_prompt
        agent_kernel_prompt
        agent_kernel_foundation
        GTest::gtest_main
)

target_compile_features(agent_kernel_agent_model_tests PRIVATE cxx_std_20)

add_test(NAME AgentModelTest COMMAND agent_kernel_agent_model_tests)

# P1-IS008 Rev1.0 Chapters 16/18 static boundary check:
# - AgentModel headers/sources include no Runtime internals, no
#   Memory/Context/Planner/Tool/Agent/Prompt/FWA internals, and
#   no concrete Model-provider SDK.
# - The AgentModel build target links only the Model target and
#   the Kernel Foundation.
# - No ModelAction, Tool-execution, Runtime, or second
#   coordination API exists on the AgentModel surface.
add_test(NAME AgentModelBoundaryCheck
    COMMAND ${CMAKE_COMMAND}
        -DAGENT_MODEL_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/agent_model
        -DAGENT_MODEL_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../src/agent_model
        -DAGENT_MODEL_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_agent_model,LINK_LIBRARIES>
        -DAGENT_MODEL_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_agent_model,INTERFACE_LINK_LIBRARIES>
        -P ${CMAKE_CURRENT_SOURCE_DIR}/check_agent_model_boundaries.cmake
)
