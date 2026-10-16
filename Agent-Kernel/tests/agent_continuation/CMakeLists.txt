# ============================================================
# tests/agent_continuation/CMakeLists.txt - TASK 3.5
# ============================================================
# TASK 3.5 test target plus the static boundary check for the
# Agent-owned observation-driven continuation integration.
#
# The production target (agent_kernel_agent_continuation) links
# ONLY the sanctioned Agent-owned surfaces; it never links
# agent_kernel_runtime directly (TASK 3.5 Contract section 15;
# Implementation Plan section 21).
#
# The TEST target links the Runtime directly because the test
# is the integration bootstrap (TASK 3.1 section 17 pattern):
# it constructs the real Runtime and wires the real adapter.
# That is test-side wiring, not production Agent code.
# ============================================================

find_package(GTest REQUIRED)

add_executable(agent_continuation_test
    agent_continuation_composition_test.cpp
)

target_include_directories(agent_continuation_test
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        ${CMAKE_CURRENT_SOURCE_DIR}/../model
)

target_link_libraries(agent_continuation_test
    PRIVATE
        agent_kernel_agent_continuation
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

target_compile_features(agent_continuation_test PRIVATE cxx_std_20)

# Repository root for content-preservation assertions
# (FWA / TASK 3.3 / TASK 3.4 / authority / creep check).
target_compile_definitions(agent_continuation_test PRIVATE
    TASK35_REPO_ROOT="${CMAKE_CURRENT_SOURCE_DIR}/../.."
)

add_test(NAME AgentContinuationTest COMMAND agent_continuation_test)

# Static boundary verification (TASK 3.5 Contract section 15;
# Implementation Plan section 19):
# - The production target links ONLY the sanctioned set and does
#   NOT link agent_kernel_runtime / agent_kernel_runtime_integration
#   / agent_kernel_runtime_backed_agent directly or through
#   interface.
# - The new headers/sources contain no Runtime include, no
#   Scheduler / Executor / CapabilityResolver / EventBus types,
#   and no quoted includes escaping the module.
# - No FWA test seam (ModelBoundary / ToolExecutionBoundary) and
#   no ExecutionSupervision production-path expansion reference.
# - No test header is included in production code.
add_test(NAME AgentContinuationBoundaryCheck
    COMMAND ${CMAKE_COMMAND}
        -DAC_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/agent_continuation
        -DAC_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../src/agent_continuation
        -DAC_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_agent_continuation,LINK_LIBRARIES>
        -DAC_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_agent_continuation,INTERFACE_LINK_LIBRARIES>
        -P ${CMAKE_CURRENT_SOURCE_DIR}/check_agent_continuation_boundaries.cmake
)
