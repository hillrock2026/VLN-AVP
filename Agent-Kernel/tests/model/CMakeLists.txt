# ============================================================
# tests/model/CMakeLists.txt - P1-IS008 Rev1.0 Model tests
# ============================================================
# Unit, ModelResult, deterministic, boundary, and determinism
# tests (Chapters 19.1, 19.2, 19.4, 19.5) plus a static
# dependency/Runtime-boundary check (Chapters 16, 18).
# ============================================================

find_package(GTest REQUIRED)

add_executable(agent_kernel_model_tests
    model_identity_test.cpp
    model_input_test.cpp
    model_state_test.cpp
    model_result_test.cpp
    deterministic_model_test.cpp
    model_boundary_test.cpp
)

target_include_directories(agent_kernel_model_tests
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
)

target_link_libraries(agent_kernel_model_tests
    PRIVATE
        agent_kernel_model
        agent_kernel_foundation
        GTest::gtest_main
)

target_compile_features(agent_kernel_model_tests PRIVATE cxx_std_20)

add_test(NAME ModelTest COMMAND agent_kernel_model_tests)

# P1-IS008 Rev1.0 Chapters 16/18 static boundary check:
# - Model headers/sources include no Runtime internals, no
#   Memory/Context/Planner/Tool/Agent/Prompt internals, and no
#   concrete Model-provider SDK.
# - The Model build target links only the Kernel Foundation.
# - No registry/router/scheduler/executor infrastructure and no
#   Tool-execution surface exists on the Model boundary.
add_test(NAME ModelBoundaryCheck
    COMMAND ${CMAKE_COMMAND}
        -DMODEL_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/model
        -DMODEL_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../src/model
        -DMODEL_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_model,LINK_LIBRARIES>
        -DMODEL_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_model,INTERFACE_LINK_LIBRARIES>
        -P ${CMAKE_CURRENT_SOURCE_DIR}/check_model_boundaries.cmake
)
