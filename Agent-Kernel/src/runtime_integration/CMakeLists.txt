# ============================================================
# src/runtime_integration/CMakeLists.txt - TASK 2 §13 /
# TASK 3.1 §21 integration-layer target
# ============================================================
# agent_kernel_runtime_integration is the ONLY production target
# that links the Runtime (T3.2-AC-005/016). The adapter header is
# Runtime-free (forward declaration only); the Runtime link stays
# private to this target.
# ============================================================

add_library(agent_kernel_runtime_integration STATIC
    runtime_public_api_adapter.cpp
)

target_include_directories(agent_kernel_runtime_integration
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_link_libraries(agent_kernel_runtime_integration
    PUBLIC
        agent_kernel
    PRIVATE
        agent_kernel_runtime
)

target_compile_features(agent_kernel_runtime_integration PUBLIC cxx_std_20)