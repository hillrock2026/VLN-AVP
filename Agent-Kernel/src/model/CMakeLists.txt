# ============================================================
# src/model/CMakeLists.txt - Model implementation boundary
# (P1-IS008 Rev1.0)
# ============================================================
# agent_kernel_model is the explicit Model implementation
# target. It links ONLY the Kernel Foundation:
#   - no Agent implementation
#   - no Memory/Context/Planner/Tool implementation
#   - no Runtime Adapter or Runtime Public API binding
#   - no Runtime internals
#   - no concrete Model-provider SDK
#
# P1-IS008 Rev1.0 Chapters 16, 18 permitted dependency:
#   agent_kernel_model -> agent_kernel_foundation
#
# The Agent-facing Model coordination boundary lives in
# src/agent_model (agent_kernel_agent_model) and is expressed
# without a reverse Model -> Agent target dependency.
# ============================================================

add_library(agent_kernel_model STATIC
    model_identity.cpp
    model_input.cpp
    model_result.cpp
    model_state.cpp
)

target_include_directories(agent_kernel_model
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_compile_features(agent_kernel_model PUBLIC cxx_std_20)

# P1-IS008: the Model target SHALL depend only on the Kernel
# Foundation. No Runtime, Scheduler, Executor, Tool, Memory,
# Context, Planner, Agent, or provider SDK target is linked
# (Chapters 16, 18).
target_link_libraries(agent_kernel_model PUBLIC agent_kernel_foundation)
