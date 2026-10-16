add_library(agent_kernel_runtime STATIC
    src/runtime.cpp
    src/runtime_configuration.cpp
    src/runtime_state_machine.cpp
    src/runtime_lifecycle_manager.cpp
    src/runtime_scheduler.cpp
    src/runtime_executor.cpp
    src/capability_resolver.cpp
    src/runtime_event.cpp
    src/event_bus.cpp
)

target_include_directories(agent_kernel_runtime
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:>
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../include>
)

target_link_libraries(agent_kernel_runtime PUBLIC agent_kernel)
target_compile_features(agent_kernel_runtime PUBLIC cxx_std_20)

# P0R0006 — Walking Skeleton demonstration (executable end-to-end validation).
if(AK_BUILD_EXAMPLES)
    add_executable(walking_skeleton_demo
        demo/walking_skeleton_demo.cpp
    )
    target_link_libraries(walking_skeleton_demo
        PRIVATE
            agent_kernel_runtime
            agent_kernel
    )
    target_compile_features(walking_skeleton_demo PRIVATE cxx_std_20)
    add_test(NAME WalkingSkeletonDemo COMMAND walking_skeleton_demo)
endif()

if(AK_BUILD_TESTS)
    add_subdirectory(tests)
endif()