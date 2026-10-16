# ============================================================
# src/foundation/CMakeLists.txt - Kernel Foundation boundary
# ============================================================
# P1-IS001 Kernel Foundation implementation boundary.
#
# agent_kernel_foundation is the explicit Foundation build
# target. It links against NOTHING:
#   - no Agent implementation
#   - no Memory/Context/Planner/Tool implementation
#   - no Execution Composition
#   - no Runtime Adapter
#   - no Runtime internals or Runtime Public API
#
# The empty link boundary is a deliberate, reviewable P1-IS001
# constraint (Chapter 8 - Dependency Direction). Compilation
# into a shared binary must not erase this logical boundary.
# ============================================================

add_library(agent_kernel_foundation STATIC
    kernel_observer.cpp
)

target_include_directories(agent_kernel_foundation
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_compile_features(agent_kernel_foundation PUBLIC cxx_std_20)

# P1-IS001: the Foundation target SHALL NOT link against any
# consuming subsystem or Runtime target.
# (intentionally no target_link_libraries)