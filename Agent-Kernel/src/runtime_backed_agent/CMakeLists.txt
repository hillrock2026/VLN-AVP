# ============================================================
# src/runtime_backed_agent/CMakeLists.txt - TASK 3.3
# ============================================================
# agent_kernel_runtime_backed_agent is the Agent-owned
# Runtime-backed execution composition target. It links the
# sanctioned integration bridge (agent_kernel_runtime_integration)
# and the existing Context target; it never includes Runtime
# internals and never links agent_kernel_runtime directly.
# ============================================================

add_library(agent_kernel_runtime_backed_agent STATIC
    runtime_backed_execution_composition.cpp
)

target_include_directories(agent_kernel_runtime_backed_agent
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_compile_features(agent_kernel_runtime_backed_agent PUBLIC cxx_std_20)

target_link_libraries(agent_kernel_runtime_backed_agent
    PUBLIC
        agent_kernel_runtime_integration
        agent_kernel_context
)
