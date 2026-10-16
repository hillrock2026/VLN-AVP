# ============================================================
# src/agent_continuation/CMakeLists.txt - TASK 3.5
# ============================================================
# agent_kernel_agent_continuation is the Agent-owned bounded
# continuation composition target.
#
# It links ONLY the sanctioned Agent-owned surfaces:
#   agent_kernel_model_to_runtime (TASK 3.4, REUSED UNCHANGED)
#   agent_kernel_context
#   agent_kernel_agent_prompt
#   agent_kernel_foundation
#
# It never includes Runtime internals and never links
# agent_kernel_runtime directly (TASK 3.5 Contract section 15;
# Implementation Plan section 21). Runtime execution is reached
# only through the CLOSED TASK 3.3 composition via the CLOSED
# TASK 3.4 composition.
# ============================================================

add_library(agent_kernel_agent_continuation STATIC
    agent_continuation_composition.cpp
)

target_include_directories(agent_kernel_agent_continuation
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_compile_features(agent_kernel_agent_continuation PUBLIC cxx_std_20)

target_link_libraries(agent_kernel_agent_continuation
    PUBLIC
        agent_kernel_model_to_runtime
        agent_kernel_context
        agent_kernel_agent_prompt
        agent_kernel_foundation
)
