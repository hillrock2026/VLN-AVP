# ============================================================
# src/model_to_runtime/CMakeLists.txt - TASK 3.4
# ============================================================
# agent_kernel_model_to_runtime is the Agent-owned
# Model-to-Runtime decision integration composition target.
#
# It links ONLY the sanctioned Agent-owned surfaces and the
# CLOSED TASK 3.3 composition (REUSED UNCHANGED):
#   agent_kernel_runtime_backed_agent (TASK 3.3)
#   agent_kernel_agent_model
#   agent_kernel_agent_prompt
#   agent_kernel_context
#   agent_kernel_foundation
#
# It never includes Runtime internals and never links
# agent_kernel_runtime directly (TASK 3.4 Contract section 8;
# Implementation Plan section 17).
# ============================================================

add_library(agent_kernel_model_to_runtime STATIC
    model_result_interpreter.cpp
    model_to_runtime_decision_composition.cpp
)

target_include_directories(agent_kernel_model_to_runtime
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_compile_features(agent_kernel_model_to_runtime PUBLIC cxx_std_20)

target_link_libraries(agent_kernel_model_to_runtime
    PUBLIC
        agent_kernel_runtime_backed_agent
        agent_kernel_agent_model
        agent_kernel_agent_prompt
        agent_kernel_context
        agent_kernel_foundation
)