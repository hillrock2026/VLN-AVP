# ============================================================
# src/agent_model/CMakeLists.txt - Agent-owned Model
# coordination boundary (P1-IS008 Rev1.0)
# ============================================================
# agent_kernel_agent_model is the Agent-owned production
# coordination surface (AgentModelBinding, AgentModelHost).
# It links ONLY:
#   - agent_kernel_model (direction Agent -> Model)
#   - agent_kernel_foundation
#
# P1-IS008 Rev1.0 Chapters 15, 16 permitted dependencies:
#   agent_kernel_agent_model -> agent_kernel_model,
#                               agent_kernel_foundation
#
# It SHALL NOT be linked into agent_kernel_model (no reverse
# dependency), carries no Runtime dependency, and contains no
# concrete provider SDK type (Chapters 11, 16).
# ============================================================

add_library(agent_kernel_agent_model STATIC
    agent_model_binding.cpp
    agent_model_host.cpp
)

target_include_directories(agent_kernel_agent_model
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_compile_features(agent_kernel_agent_model PUBLIC cxx_std_20)

# P1-IS008: Agent-owned Model coordination depends on the
# Model target and the Kernel Foundation ONLY.
target_link_libraries(agent_kernel_agent_model
    PUBLIC
        agent_kernel_model
        agent_kernel_foundation
)
