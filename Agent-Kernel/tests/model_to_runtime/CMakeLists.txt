# ============================================================
# tests/model_to_runtime/CMakeLists.txt - TASK 3.4
# ============================================================
# TASK 3.4 test target plus the static boundary check for the
# Agent-owned Model-to-Runtime decision integration.
#
# The production target (agent_kernel_model_to_runtime) links
# ONLY the sanctioned Agent-owned surfaces and the CLOSED
# TASK 3.3 composition; it never links agent_kernel_runtime
# directly (TASK 3.4 Contract section 8; Plan section 15.3).
#
# The TEST target links the Runtime directly because the test
# is the integration bootstrap (TASK 3.1 section 17 pattern):
# it constructs the real Runtime and wires the real adapter.
# That is test-side wiring, not production Agent code.
# ============================================================

find_package(GTest REQUIRED)

add_executable(model_to_runtime_test
    model_to_runtime_composition_test.cpp
)

target_include_directories(model_to_runtime_test
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        ${CMAKE_CURRENT_SOURCE_DIR}/../model
)

target_link_libraries(model_to_runtime_test
    PRIVATE
        agent_kernel_model_to_runtime
        agent_kernel_runtime_backed_agent
        agent_kernel_runtime_integration
        agent_kernel_runtime
        agent_kernel_agent_model
        agent_kernel_agent_prompt
        agent_kernel_prompt
        agent_kernel_model
        agent_kernel_agent
        agent_kernel_context
        agent_kernel
        agent_kernel_foundation
        GTest::gtest_main
)

target_compile_features(model_to_runtime_test PRIVATE cxx_std_20)

# Repository root for content-preservation assertions (FWA / authority / creep check).
target_compile_definitions(model_to_runtime_test PRIVATE
    TASK34_REPO_ROOT="${CMAKE_CURRENT_SOURCE_DIR}/../.."
)

add_test(NAME ModelToRuntimeTest COMMAND model_to_runtime_test)

# Static boundary verification (TASK 3.4 Contract section 8;
# Implementation Plan section 15.3):
# - The production target links ONLY the sanctioned set and does
#   NOT link agent_kernel_runtime directly or through interface.
# - The new headers/sources contain no Runtime include, no
#   Scheduler / Executor / CapabilityResolver / EventBus types,
#   and no quoted includes escaping the module.
# - The Model boundary is preserved (no Tool / Context / Agent
#   lifecycle / Runtime calls from Model-touching code).
# - No test header is included in production code.
add_test(NAME ModelToRuntimeBoundaryCheck
    COMMAND ${CMAKE_COMMAND}
        -DMRT_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/model_to_runtime
        -DMRT_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../src/model_to_runtime
        -DMRT_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_model_to_runtime,LINK_LIBRARIES>
        -DMRT_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_model_to_runtime,INTERFACE_LINK_LIBRARIES>
        -P ${CMAKE_CURRENT_SOURCE_DIR}/check_model_to_runtime_boundaries.cmake
)
