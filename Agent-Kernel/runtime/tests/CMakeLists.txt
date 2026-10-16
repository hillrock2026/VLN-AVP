find_package(GTest REQUIRED)

add_executable(runtime_test
    runtime_test.cpp
    runtime_state_machine_test.cpp
    runtime_lifecycle_test.cpp
    runtime_scheduler_test.cpp
    runtime_executor_test.cpp
    capability_resolver_test.cpp
    event_bus_test.cpp
    runtime_integration_test.cpp
)

target_include_directories(runtime_test
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../include>
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
)

target_link_libraries(runtime_test
    PRIVATE
        agent_kernel_runtime
        agent_kernel
        GTest::gtest_main
)

target_compile_features(runtime_test PUBLIC cxx_std_20)
add_test(NAME RuntimeTest COMMAND runtime_test)
