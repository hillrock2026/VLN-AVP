# ============================================================
# tests/memory/CMakeLists.txt - P1-IS003 Memory tests
# ============================================================
# Behavioral and structural conformance tests for the Phase 2
# Memory implementation, plus a static dependency/Runtime-
# boundary check (P1-IS003 Chapter 18/19).
# ============================================================

find_package(GTest REQUIRED)

add_executable(memory_test
    memory_identity_test.cpp
    memory_lifecycle_test.cpp
    memory_state_test.cpp
    memory_objects_test.cpp
    memory_services_test.cpp
    memory_provider_test.cpp
    memory_agent_contract_test.cpp
    memory_extensions_test.cpp
    memory_runtime_isolation_test.cpp
    ownership_dependency_test.cpp
    foundation_reuse_test.cpp
    memory_boundary_validator_test.cpp
)

target_include_directories(memory_test
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
)

target_link_libraries(memory_test
    PRIVATE
        agent_kernel_memory
        agent_kernel_foundation
        GTest::gtest_main
)

target_compile_features(memory_test PRIVATE cxx_std_20)

add_test(NAME MemoryTest COMMAND memory_test)

# P1-IS003 Chapter 13/18 static boundary check:
# - Memory headers/sources include no Runtime internals and no
#   Agent/Context/Planner/Tool internals.
# - The Memory build target links only the Kernel Foundation.
add_test(NAME MemoryBoundaryCheck
    COMMAND ${CMAKE_COMMAND}
        -DMEMORY_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/memory
        -DMEMORY_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../src/memory
        -DMEMORY_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_memory,LINK_LIBRARIES>
        -DMEMORY_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_memory,INTERFACE_LINK_LIBRARIES>
        -P ${CMAKE_CURRENT_SOURCE_DIR}/check_memory_boundaries.cmake
)