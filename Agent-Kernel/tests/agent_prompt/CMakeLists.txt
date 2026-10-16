# ============================================================
# tests/agent_prompt/CMakeLists.txt - P1-IS007 Rev1.1
# Agent-Prompt boundary tests
# ============================================================
# agent_kernel_agent_prompt_tests: AgentPromptBinding behavior
# and REAL Agent -> AgentPromptHost -> AgentPromptBinding ->
# Prompt -> PromptResult end-to-end composition
# (P1-IS007 Rev1.1 Chapters 19, 33).
# ============================================================

find_package(GTest REQUIRED)

add_executable(agent_kernel_agent_prompt_tests
    agent_prompt_binding_test.cpp
    agent_prompt_host_test.cpp
    agent_prompt_integration_test.cpp
)

target_include_directories(agent_kernel_agent_prompt_tests
    PRIVATE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
)

target_link_libraries(agent_kernel_agent_prompt_tests
    PRIVATE
        agent_kernel_agent_prompt
        agent_kernel_prompt
        agent_kernel_foundation
        GTest::gtest_main
)

target_compile_features(agent_kernel_agent_prompt_tests PRIVATE cxx_std_20)

add_test(NAME AgentPromptTest COMMAND agent_kernel_agent_prompt_tests)

# Agent-side host boundary check: agent_kernel_agent_prompt
# links ONLY agent_kernel_prompt + agent_kernel_foundation,
# contains no Runtime dependency, and exposes no public
# Prompt() accessor (P1-IS007 Rev1.1 Chapters 19.3, 26, 32).
add_test(NAME AgentPromptBoundaryCheck
    COMMAND ${CMAKE_COMMAND}
        -DAGENT_PROMPT_INCLUDE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../include/agent_kernel/agent_prompt
        -DAGENT_PROMPT_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../../src/agent_prompt
        -DAGENT_PROMPT_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_agent_prompt,LINK_LIBRARIES>
        -DAGENT_PROMPT_INTERFACE_LINK_LIBS=$<TARGET_PROPERTY:agent_kernel_agent_prompt,INTERFACE_LINK_LIBRARIES>
        -P ${CMAKE_CURRENT_SOURCE_DIR}/check_agent_prompt_boundaries.cmake
)