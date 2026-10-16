# ============================================================
# tests/foundation/CMakeLists.txt - P1-IS001 Foundation tests
# ============================================================
# Behavioral and structural conformance tests for the Kernel
# Foundation, plus a static dependency/Runtime-boundary check.
# ============================================================

find_package(GTest REQUIRED)

add_executable(foundation_test
    identity_test.cpp
    handle_object_test.cpp
    observer_test.cpp
    lifecycle_diagnostics_test.cpp
    registry_test.cpp
    conformance_test.cpp
)

target_include_directories(foundation_test
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
)

target_link_libraries(foundation_test
    PRIVATE
        agent_kernel_foundation
        GTest::gtest_main
)

target_compile_features(foundation_test PRIVATE cxx_std_20)

add_test(NAME FoundationTest COMMAND foundation_test)

# P1-IS001 Chapter 29 / Chapter 34 static boundary check:
# - Foundation includes no subsystem or Runtime internals.
# - The Foundation build target links against nothing.
add_test(NAME FoundationBoundaryCheck
    COMMAND ${CMAKE_COMMAND}
        -DFOUNDATION_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/foundation
        -DFOUNDATION_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../src/foundation
        -DFOUNDATION_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_foundation,LINK_LIBRARIES>
        -DFOUNDATION_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_foundation,INTERFACE_LINK_LIBRARIES>
        -P ${CMAKE_CURRENT_SOURCE_DIR}/check_foundation_boundaries.cmake
)