# ============================================================
# tests/runtime_integration/CMakeLists.txt - TASK 3.1 §20/§21
# ============================================================
# New TASK 3.2 integration test target plus the static
# Agent/Runtime integration boundary check (CC-8).
# ============================================================

find_package(GTest REQUIRED)

add_executable(runtime_integration_test
    runtime_integration_test.cpp
    k0_execution_authority_factory_test.cpp
)

target_include_directories(runtime_integration_test
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
)

target_link_libraries(runtime_integration_test
    PRIVATE
        agent_kernel_runtime_integration
        agent_kernel_runtime
        agent_kernel
        agent_kernel_model
        agent_kernel_context
        agent_kernel_foundation
        GTest::gtest_main
)

target_compile_features(runtime_integration_test PRIVATE cxx_std_20)

add_test(NAME RuntimeIntegrationTest COMMAND runtime_integration_test)

# Static boundary verification (TASK 3.1 §20/§21; CC-8):
# - Agent subsystem + FWA composition targets stay Runtime-free.
# - Tool / Planner / Model / Context / Memory / Prompt production
#   targets stay Runtime-free.
# - The integration adapter is the sole production Runtime link,
#   and its public header stays Runtime-free.
add_test(NAME RuntimeIntegrationBoundaryCheck
    COMMAND ${CMAKE_COMMAND}
        -DRI_AGENT_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/agent
        -DRI_FWA_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/fwa
        -DRI_ADAPTER_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/runtime_integration
        -DRI_ADAPTER_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../src/runtime_integration
        -DRI_INTEGRATION_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_runtime_integration,LINK_LIBRARIES>
        -DRI_INTEGRATION_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_runtime_integration,INTERFACE_LINK_LIBRARIES>
        -DRI_AGENT_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_agent,LINK_LIBRARIES>
        -DRI_AGENT_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_agent,INTERFACE_LINK_LIBRARIES>
        -DRI_FWA_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_first_working_agent,LINK_LIBRARIES>
        -DRI_FWA_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_first_working_agent,INTERFACE_LINK_LIBRARIES>
        -DRI_TOOL_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_tool,LINK_LIBRARIES>
        -DRI_PLANNER_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_planner,LINK_LIBRARIES>
        -DRI_MODEL_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_model,LINK_LIBRARIES>
        -DRI_CONTEXT_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_context,LINK_LIBRARIES>
        -DRI_MEMORY_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_memory,LINK_LIBRARIES>
        -DRI_PROMPT_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_prompt,LINK_LIBRARIES>
        -P ${CMAKE_CURRENT_SOURCE_DIR}/check_runtime_integration_boundaries.cmake
)