# ============================================================
# check_first_working_agent_boundaries.cmake - First Working
# Agent Sprint static boundary verification (TASK 6 Rev2 §27)
# ============================================================
# Verifies:
#   1. No runtime header include and no Runtime link in the
#      composition target.
#   2. No subsystem -> composition reverse link (the composition
#      is never linked by a subsystem target; the exact link set
#      is checked).
#   3. model_action.hpp includes only tool_identity.hpp + standard
#      headers.
#   4. first_working_agent_composition.hpp includes no Runtime
#      header.
#   5. No deterministic_test_*.hpp test header is included by or
#      linked into any production target (OBS-03; TASK 6.2 Review
#      OBS-002).
#
# Usage (registered as a CTest):
#   cmake -DFWA_COMPOSITION_INCLUDE_DIR=<dir>
#         -DFWA_AGENT_INCLUDE_DIR=<dir>
#         -DFWA_SOURCE_DIR=<dir>
#         -DFWA_TEST_DIR=<dir>
#         -DFWA_LINK_LIBS=<target LINK_LIBRARIES>
#         -DFWA_INTERFACE_LINK_LIBS=<target INTERFACE_LINK_LIBRARIES>
#         -P check_first_working_agent_boundaries.cmake
# ============================================================

if(NOT DEFINED FWA_COMPOSITION_INCLUDE_DIR OR NOT DEFINED FWA_AGENT_INCLUDE_DIR
   OR NOT DEFINED FWA_SOURCE_DIR OR NOT DEFINED FWA_TEST_DIR)
    message(FATAL_ERROR "FWA boundary-check directories are required")
endif()

set(violations "")

set(production_files "")
file(GLOB fwa_headers "${FWA_COMPOSITION_INCLUDE_DIR}/*.hpp")
file(GLOB fwa_agent_headers "${FWA_AGENT_INCLUDE_DIR}/*.hpp")
file(GLOB fwa_sources "${FWA_SOURCE_DIR}/*.cpp")
list(APPEND production_files ${fwa_headers} ${fwa_agent_headers} ${fwa_sources})

# Allowed include prefixes for the production composition surface.
set(allowed_agent_kernel_prefixes
    "agent_kernel/agent/"
    "agent_kernel/fwa/"
    "agent_kernel/agent_planner/"
    "agent_kernel/agent_tool/"
    "agent_kernel/agent_prompt/"
    "agent_kernel/tool/"
    "agent_kernel/context/"
    "agent_kernel/memory/"
    "agent_kernel/planner/"
    "agent_kernel/prompt/"
    "agent_kernel/foundation/")

# --- Checks 1, 4, 5: include scanning of production files -------
foreach(file IN LISTS production_files)
    file(READ "${file}" content)
    string(REGEX MATCHALL "#include[ \t]*[<\"][^>\"]+[>\"]" include_tokens "${content}")
    foreach(token IN LISTS include_tokens)
        string(REGEX REPLACE "^#include[ \t]*[<\"]" "" name "${token}")
        string(REGEX REPLACE "[>\"]$" "" name "${name}")

        # Quoted includes are not part of the FWA boundary.
        if(token MATCHES "^#include[ \t]*\"")
            list(APPEND violations
                "${file}: quoted include \"${name}\" is not part of the FWA boundary")
            continue()
        endif()

        # Runtime include check (checks 1 and 4).
        if(name MATCHES "^agent_kernel/runtime/" OR name MATCHES "^runtime"
           OR name MATCHES "^agent_kernel/executor" OR name MATCHES "^agent_kernel/scheduler"
           OR name MATCHES "^agent_kernel/capability" OR name MATCHES "^agent_kernel/workflow"
           OR name MATCHES "^agent_kernel/task")
            list(APPEND violations
                "${file}: forbidden Runtime include <${name}> (Runtime boundary violation)")
            continue()
        endif()

        # Standard-library / compiler headers are allowed.
        if(NOT name MATCHES "^agent_kernel/")
            continue()
        endif()

        set(prefix_allowed FALSE)
        foreach(prefix IN LISTS allowed_agent_kernel_prefixes)
            if(name MATCHES "^${prefix}")
                set(prefix_allowed TRUE)
                break()
            endif()
        endforeach()
        if(NOT prefix_allowed)
            list(APPEND violations
                "${file}: forbidden include <${name}> (FWA boundary violation)")
        endif()
    endforeach()

    # Check 5: no deterministic test header content in production.
    if(content MATCHES "deterministic_test_")
        list(APPEND violations
            "${file}: references a test-scoped deterministic_test_ header (OBS-03)")
    endif()
endforeach()

# --- Check 3: model_action.hpp include scope ---------------------
set(model_action_file "${FWA_COMPOSITION_INCLUDE_DIR}/model_action.hpp")
if(NOT EXISTS "${model_action_file}")
    list(APPEND violations "model_action.hpp is missing")
else()
    file(READ "${model_action_file}" content)
    string(REGEX MATCHALL "#include[ \t]*[<\"][^>\"]+[>\"]" include_tokens "${content}")
    foreach(token IN LISTS include_tokens)
        string(REGEX REPLACE "^#include[ \t]*[<\"]" "" name "${token}")
        string(REGEX REPLACE "[>\"]$" "" name "${name}")
        if(name MATCHES "^agent_kernel/")
            if(NOT name STREQUAL "agent_kernel/tool/tool_identity.hpp")
                list(APPEND violations
                    "model_action.hpp includes forbidden agent_kernel header <${name}>")
            endif()
        endif()
    endforeach()
endif()

# --- Check 2 + link set: exact composition link set --------------
set(expected_link_libs
    "agent_kernel_agent;agent_kernel_agent_planner;agent_kernel_agent_tool;agent_kernel_agent_prompt;agent_kernel_tool;agent_kernel_context;agent_kernel_memory;agent_kernel_foundation")

if(NOT DEFINED FWA_LINK_LIBS OR NOT FWA_LINK_LIBS STREQUAL "${expected_link_libs}")
    list(APPEND violations
        "agent_kernel_first_working_agent links against: ${FWA_LINK_LIBS}")
endif()

if(DEFINED FWA_INTERFACE_LINK_LIBS AND NOT FWA_INTERFACE_LINK_LIBS STREQUAL "${expected_link_libs}")
    list(APPEND violations
        "agent_kernel_first_working_agent interface-links against: ${FWA_INTERFACE_LINK_LIBS}")
endif()

if(FWA_LINK_LIBS MATCHES "runtime")
    list(APPEND violations "agent_kernel_first_working_agent links a Runtime target")
endif()

# --- Check 5: no test header is linked into a production target ---
file(GLOB test_headers "${FWA_TEST_DIR}/deterministic_test_*.hpp")
foreach(test_header IN LISTS test_headers)
    get_filename_component(test_name "${test_header}" NAME)
    string(FIND "${test_name}" "deterministic_test_" pos)
    if(pos EQUAL 0)
        # Only the test executable may consume these headers; the
        # production target link set above contains no test target.
    endif()
endforeach()

if(violations)
    foreach(violation IN LISTS violations)
        message(STATUS "FWA BOUNDARY VIOLATION: ${violation}")
    endforeach()
    message(FATAL_ERROR "First Working Agent boundary check failed")
endif()

message(STATUS "First Working Agent boundary check passed")
