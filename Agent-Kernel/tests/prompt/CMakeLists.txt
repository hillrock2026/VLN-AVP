# ============================================================
# tests/prompt/CMakeLists.txt - P1-IS007 Rev1.1 Prompt tests
# ============================================================
# Behavioral and structural conformance tests for the Prompt
# implementation, plus a static dependency/Runtime-boundary
# check (P1-IS007 Rev1.1 Chapters 33-36).
# ============================================================

find_package(GTest REQUIRED)

add_executable(agent_kernel_prompt_tests
    prompt_identity_test.cpp
    prompt_section_test.cpp
    prompt_variable_test.cpp
    prompt_binding_test.cpp
    prompt_definition_test.cpp
    prompt_assembly_test.cpp
    prompt_result_test.cpp
    prompt_validation_test.cpp
    prompt_boundary_test.cpp
    prompt_concurrency_test.cpp
)

target_include_directories(agent_kernel_prompt_tests
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
)

target_link_libraries(agent_kernel_prompt_tests
    PRIVATE
        agent_kernel_prompt
        agent_kernel_foundation
        GTest::gtest_main
)

target_compile_features(agent_kernel_prompt_tests PRIVATE cxx_std_20)

add_test(NAME PromptTest COMMAND agent_kernel_prompt_tests)

# P1-IS007 Rev1.1 Chapters 28/36 static boundary check:
# - Prompt headers/sources include no Runtime internals, no
#   Memory/Context/Planner/Tool/Agent internals, and no
#   concrete Model-provider SDK.
# - The Prompt build target links only the Kernel Foundation.
# - No mirror domain models and no active-retrieval surface.
add_test(NAME PromptBoundaryCheck
    COMMAND ${CMAKE_COMMAND}
        -DPROMPT_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/prompt
        -DPROMPT_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../src/prompt
        -DPROMPT_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_prompt,LINK_LIBRARIES>
        -DPROMPT_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_prompt,INTERFACE_LINK_LIBRARIES>
        -P ${CMAKE_CURRENT_SOURCE_DIR}/check_prompt_boundaries.cmake
)