# ============================================================
# tests/tool/CMakeLists.txt - P1-IS006 Rev2 Tool tests
# ============================================================
# Behavioral and structural conformance tests for the Phase 4
# Tool implementation, plus a static dependency/Runtime-
# boundary check (P1-IS006 Rev2 Chapters 33-34, TOL-011).
# ============================================================

find_package(GTest REQUIRED)

add_executable(agent_kernel_tool_tests
    tool_identity_test.cpp
    tool_lifecycle_test.cpp
    tool_state_test.cpp
    tool_capability_test.cpp
    tool_registration_test.cpp
    tool_discovery_test.cpp
    tool_provider_test.cpp
    tool_services_test.cpp
    tool_extension_test.cpp
    tool_concurrency_test.cpp
    tool_failure_test.cpp
    tool_runtime_isolation_test.cpp
)

target_include_directories(agent_kernel_tool_tests
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
)

target_link_libraries(agent_kernel_tool_tests
    PRIVATE
        agent_kernel_tool
        agent_kernel_foundation
        GTest::gtest_main
)

target_compile_features(agent_kernel_tool_tests PRIVATE cxx_std_20)

add_test(NAME ToolTest COMMAND agent_kernel_tool_tests)

# P1-IS006 Rev2 Chapters 33.14/34 static boundary check:
# - Tool headers/sources include no Runtime internals and no
#   Agent/Context/Planner/Memory internals.
# - The Tool build target links only the Kernel Foundation.
add_test(NAME ToolBoundaryCheck
    COMMAND ${CMAKE_COMMAND}
        -DTOOL_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/tool
        -DTOOL_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../src/tool
        -DTOOL_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_tool,LINK_LIBRARIES>
        -DTOOL_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_tool,INTERFACE_LINK_LIBRARIES>
        -P ${CMAKE_CURRENT_SOURCE_DIR}/check_tool_boundaries.cmake
)