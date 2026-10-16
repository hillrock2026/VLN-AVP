# ============================================================
# tests/runtime_backed_agent/CMakeLists.txt - TASK 3.3
# ============================================================
# TASK 3.3 test target plus the static boundary check for the
# Agent-owned runtime-backed execution composition.
#
# The composition target (agent_kernel_runtime_backed_agent)
# links ONLY the sanctioned integration bridge
# (agent_kernel_runtime_integration) and Context. It never
# links agent_kernel_runtime directly and never includes
# Runtime internals.
#
# The TEST target links the Runtime directly because the test
# is the integration bootstrap (TASK 3.1 section 17 pattern):
# it constructs the real Runtime and wires the real adapter.
# That is test-side wiring, not production Agent code.
# ============================================================

find_package(GTest REQUIRED)

add_executable(runtime_backed_agent_test
    runtime_backed_agent_composition_test.cpp
)

target_include_directories(runtime_backed_agent_test
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
)

target_link_libraries(runtime_backed_agent_test
    PRIVATE
        agent_kernel_runtime_backed_agent
        agent_kernel_runtime_integration
        agent_kernel_runtime
        agent_kernel
        agent_kernel_context
        agent_kernel_model
        agent_kernel_foundation
        GTest::gtest_main
)

target_compile_features(runtime_backed_agent_test PRIVATE cxx_std_20)

add_test(NAME RuntimeBackedAgentTest COMMAND runtime_backed_agent_test)

# Static boundary verification (TASK 3.3 Contract 7/8; plan section 18):
# - The composition headers and sources never include Runtime
#   internals or the Runtime Public API (only the adapter
#   translation unit may include <runtime.h>).
# - The composition target links the sanctioned integration
#   bridge and does NOT link agent_kernel_runtime directly.
add_test(NAME RuntimeBackedAgentBoundaryCheck
    COMMAND ${CMAKE_COMMAND}
        -DRB_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/runtime_backed_agent
        -DRB_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../src/runtime_backed_agent
        -DRB_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_runtime_backed_agent,LINK_LIBRARIES>
        -DRB_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_runtime_backed_agent,INTERFACE_LINK_LIBRARIES>
        -P ${CMAKE_CURRENT_SOURCE_DIR}/check_runtime_backed_agent_boundaries.cmake
)