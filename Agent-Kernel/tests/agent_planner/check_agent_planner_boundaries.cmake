# ============================================================
# check_agent_planner_boundaries.cmake - P1-IS005 Agent-side
# host boundary check
# ============================================================
# Verifies that the Agent-owned production composition target
# depends ONLY on:
#   - agent_kernel_planner
#   - agent_kernel_foundation
# and that the Agent-side sources/headers carry no Runtime
# dependency and no quoted includes.
#
# Usage (registered as a CTest):
#   cmake -DAGENT_PLANNER_INCLUDE_DIR=<dir>
#         -DAGENT_PLANNER_SOURCE_DIR=<dir>
#         -DAGENT_PLANNER_LINK_LIBS=<target LINK_LIBRARIES>
#         -DAGENT_PLANNER_INTERFACE_LINK_LIBS=<target INTERFACE_LINK_LIBRARIES>
#         -P check_agent_planner_boundaries.cmake
# ============================================================

if(NOT DEFINED AGENT_PLANNER_INCLUDE_DIR OR NOT DEFINED AGENT_PLANNER_SOURCE_DIR)
    message(FATAL_ERROR "AGENT_PLANNER_INCLUDE_DIR and AGENT_PLANNER_SOURCE_DIR are required")
endif()

set(violations "")

file(GLOB_RECURSE agent_planner_headers
    "${AGENT_PLANNER_INCLUDE_DIR}/*.hpp")
file(GLOB agent_planner_sources
    "${AGENT_PLANNER_SOURCE_DIR}/*.cpp")

set(all_files ${agent_planner_headers} ${agent_planner_sources})

foreach(file IN LISTS all_files)
    file(READ "${file}" content)
    string(REGEX MATCHALL "#include[ \t]*[<\"][^>\"]+[>\"]" include_tokens "${content}")
    foreach(token IN LISTS include_tokens)
        string(REGEX REPLACE "^#include[ \t]*[<\"]" "" name "${token}")
        string(REGEX REPLACE "[>\"]$" "" name "${name}")

        if(token MATCHES "^#include[ \t]*\"")
            list(APPEND violations
                "${file}: quoted include \"${name}\" is not part of the Agent Planner boundary")
            continue()
        endif()

        # Allowed: the Agent Planner subsystem's own headers, the
        # Planner boundary, and the Kernel Foundation.
        if(name MATCHES "^agent_kernel/agent_planner/")
            continue()
        endif()
        if(name MATCHES "^agent_kernel/planner/")
            continue()
        endif()
        if(name MATCHES "^agent_kernel/foundation/")
            continue()
        endif()

        if(name MATCHES "^agent_kernel/")
            list(APPEND violations
                "${file}: forbidden subsystem/include <${name}> (host boundary violation)")
            continue()
        endif()

        if(name MATCHES "^runtime" OR name MATCHES "^capability_"
           OR name MATCHES "^scheduler" OR name MATCHES "^executor"
           OR name MATCHES "^workflow" OR name MATCHES "^task")
            list(APPEND violations
                "${file}: forbidden Runtime/subsystem include <${name}> (Runtime boundary violation)")
        endif()
    endforeach()
endforeach()

# Link-boundary check: Agent-owned host links planner + foundation ONLY.
if(NOT DEFINED AGENT_PLANNER_LINK_LIBS OR NOT AGENT_PLANNER_LINK_LIBS STREQUAL "agent_kernel_planner;agent_kernel_foundation")
    list(APPEND violations
        "agent_kernel_agent_planner links against: ${AGENT_PLANNER_LINK_LIBS}")
endif()

if(DEFINED AGENT_PLANNER_INTERFACE_LINK_LIBS AND NOT AGENT_PLANNER_INTERFACE_LINK_LIBS STREQUAL "agent_kernel_planner;agent_kernel_foundation")
    list(APPEND violations
        "agent_kernel_agent_planner interface-links against: ${AGENT_PLANNER_INTERFACE_LINK_LIBS}")
endif()

list(LENGTH all_files all_files_count)
if(violations)
    foreach(violation IN LISTS violations)
        message(STATUS "AGENT PLANNER BOUNDARY VIOLATION: ${violation}")
    endforeach()
    message(FATAL_ERROR "P1-IS005 Agent Planner host boundary check failed")
endif()

message(STATUS "P1-IS005 Agent Planner host boundary check passed "
               "(${all_files_count} files, no forbidden dependencies)")
