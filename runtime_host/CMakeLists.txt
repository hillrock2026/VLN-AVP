# ============================================================
# runtime_host/CMakeLists.txt - VLN-AVP real Kernel host (Phase 3B-3B)
# ============================================================
# Builds the C++ NDJSON host that owns an Agent-Kernel Runtime and executes
# IPC v1 requests through the sanctioned authorization factory.
#
# Required inputs, supplied by the caller. This file hardcodes NO machine
# path, temporary directory or user directory:
#
#   AGENT_KERNEL_SOURCE_DIR    a CLEAN Agent-Kernel source tree that exposes
#                              include/agent_kernel/runtime_integration/
#                              runtime_execution_authority.hpp
#                              (obtain e.g. with: git archive <sha> | tar -x).
#   NLOHMANN_JSON_INCLUDE_DIR  include directory containing <nlohmann/json.hpp>.
#
# The Kernel is consumed through its EXISTING CMake targets; no Runtime or
# adapter implementation is copied into VLN-AVP.
# ============================================================
cmake_minimum_required(VERSION 3.22)
project(vln_avp_kernel_host LANGUAGES CXX)

if(NOT DEFINED AGENT_KERNEL_SOURCE_DIR OR AGENT_KERNEL_SOURCE_DIR STREQUAL "")
    message(FATAL_ERROR
        "AGENT_KERNEL_SOURCE_DIR must point to a clean Agent-Kernel source tree")
endif()
if(NOT DEFINED NLOHMANN_JSON_INCLUDE_DIR OR NLOHMANN_JSON_INCLUDE_DIR STREQUAL "")
    message(FATAL_ERROR
        "NLOHMANN_JSON_INCLUDE_DIR must contain <nlohmann/json.hpp>")
endif()

get_filename_component(AGENT_KERNEL_SOURCE_DIR
    "${AGENT_KERNEL_SOURCE_DIR}" ABSOLUTE)
get_filename_component(NLOHMANN_JSON_INCLUDE_DIR
    "${NLOHMANN_JSON_INCLUDE_DIR}" ABSOLUTE)

if(NOT EXISTS "${AGENT_KERNEL_SOURCE_DIR}/CMakeLists.txt")
    message(FATAL_ERROR
        "not an Agent-Kernel source tree: ${AGENT_KERNEL_SOURCE_DIR}")
endif()
if(NOT EXISTS
   "${AGENT_KERNEL_SOURCE_DIR}/include/agent_kernel/runtime_integration/runtime_execution_authority.hpp")
    message(FATAL_ERROR
        "Agent-Kernel tree does not expose runtime_execution_authority.hpp; "
        "use a baseline that includes the runtime execution authority factory")
endif()
if(NOT EXISTS "${NLOHMANN_JSON_INCLUDE_DIR}/nlohmann/json.hpp")
    message(FATAL_ERROR
        "nlohmann/json.hpp not found under ${NLOHMANN_JSON_INCLUDE_DIR}")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Build only the Kernel libraries the host needs; no Kernel tests/examples.
set(AK_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(AK_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(AK_BUILD_PROTOTYPE OFF CACHE BOOL "" FORCE)
set(AK_ENABLE_INSTALL OFF CACHE BOOL "" FORCE)
add_subdirectory("${AGENT_KERNEL_SOURCE_DIR}"
                 "${CMAKE_CURRENT_BINARY_DIR}/_agent_kernel"
                 EXCLUDE_FROM_ALL)

add_executable(kernel_host kernel_host.cpp)
target_include_directories(kernel_host PRIVATE "${NLOHMANN_JSON_INCLUDE_DIR}")
target_link_libraries(kernel_host PRIVATE
    agent_kernel_runtime_integration
    agent_kernel_runtime
    agent_kernel
)
target_compile_features(kernel_host PRIVATE cxx_std_20)

if(MSVC)
    target_compile_options(kernel_host PRIVATE /W4 /WX /utf-8 /MP)
else()
    target_compile_options(kernel_host PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()
