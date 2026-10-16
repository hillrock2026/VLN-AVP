# ============================================================
# tests/context/CMakeLists.txt - P1-IS004 Context tests
# ============================================================
# Behavioral and structural conformance tests for the Phase 2
# Context implementation, plus a static dependency/Runtime-
# boundary check (P1-IS004 Chapter 21/22/27).
# ============================================================

find_package(GTest REQUIRED)

add_executable(context_test
    context_identity_test.cpp
    context_lifecycle_test.cpp
    context_state_test.cpp
    context_objects_test.cpp
    context_services_test.cpp
    context_agent_contract_test.cpp
    context_extensions_test.cpp
    context_runtime_isolation_test.cpp
    ownership_dependency_test.cpp
    foundation_reuse_test.cpp
    context_boundary_validator_test.cpp
)

target_include_directories(context_test
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
)

target_link_libraries(context_test
    PRIVATE
        agent_kernel_context
        agent_kernel_foundation
        GTest::gtest_main
)

target_compile_features(context_test PRIVATE cxx_std_20)

add_test(NAME ContextTest COMMAND context_test)

# P1-IS004 Chapter 21.8/21.9 static boundary check:
# - Context headers/sources include no Runtime internals and no
#   Agent/Memory/Planner/Tool internals.
# - The Context build target links only the Kernel Foundation.
add_test(NAME ContextBoundaryCheck
    COMMAND ${CMAKE_COMMAND}
        -DCONTEXT_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/context
        -DCONTEXT_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../src/context
        -DCONTEXT_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_context,LINK_LIBRARIES>
        -DCONTEXT_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_context,INTERFACE_LINK_LIBRARIES>
        -P ${CMAKE_CURRENT_SOURCE_DIR}/check_context_boundaries.cmake
)
