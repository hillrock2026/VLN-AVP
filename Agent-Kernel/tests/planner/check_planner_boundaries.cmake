# ============================================================
# check_planner_boundaries.cmake - P1-IS005 static boundary check
# ============================================================
# Verifies, without requiring a behavioral test:
#
#  1. Every Planner header and source is scanned.
#  2. No Runtime internal/public header, no Scheduler, Executor,
#     Workflow, Task, or Session usage exists in the Planner
#     boundary.
#  3. No Agent/Memory/Context/Tool internal include exists
#     (Planner SHALL NOT include ak::agent headers).
#  4. No quoted includes are used.
#  5. No Manager-style universal type is declared by the Planner
#     boundary.
#  6. The agent_kernel_planner target links only
#     agent_kernel_foundation.
#
# Usage (registered as a CTest):
#   cmake -DPLANNER_INCLUDE_DIR=<dir>
#         -DPLANNER_SOURCE_DIR=<dir>
#         -DPLANNER_LINK_LIBS=<target LINK_LIBRARIES>
#         -DPLANNER_INTERFACE_LINK_LIBS=<target INTERFACE_LINK_LIBRARIES>
#         -P check_planner_boundaries.cmake
# ============================================================

if(NOT DEFINED PLANNER_INCLUDE_DIR OR NOT DEFINED PLANNER_SOURCE_DIR)
    message(FATAL_ERROR "PLANNER_INCLUDE_DIR and PLANNER_SOURCE_DIR are required")
endif()

set(violations "")

# ------------------------------------------------------------
# 1. Include-boundary scan (all headers and sources)
# ------------------------------------------------------------
file(GLOB_RECURSE planner_headers
    "${PLANNER_INCLUDE_DIR}/*.hpp")
file(GLOB planner_sources
    "${PLANNER_SOURCE_DIR}/*.cpp")

if(NOT planner_headers)
    message(FATAL_ERROR "No Planner headers found under ${PLANNER_INCLUDE_DIR}")
endif()
if(NOT planner_sources)
    message(FATAL_ERROR "No Planner sources found under ${PLANNER_SOURCE_DIR}")
endif()

set(all_files ${planner_headers} ${planner_sources})

foreach(file IN LISTS all_files)
    file(READ "${file}" content)
    string(REGEX MATCHALL "#include[ \t]*[<\"][^>\"]+[>\"]" include_tokens "${content}")
    foreach(token IN LISTS include_tokens)
        string(REGEX REPLACE "^#include[ \t]*[<\"]" "" name "${token}")
        string(REGEX REPLACE "[>\"]$" "" name "${name}")

        # Quoted includes are not used by the Planner surface.
        if(token MATCHES "^#include[ \t]*\"")
            list(APPEND violations
                "${file}: quoted include \"${name}\" is not part of the Planner boundary")
            continue()
        endif()

        # Allowed: standard library headers, the Planner boundary,
        # and the Kernel Foundation.
        if(name MATCHES "^agent_kernel/planner/")
            continue()
        endif()
        if(name MATCHES "^agent_kernel/foundation/")
            continue()
        endif()

        if(name MATCHES "^agent_kernel/")
            list(APPEND violations
                "${file}: forbidden subsystem/include <${name}> (Agent/Memory/Context/Tool/Runtime boundary violation)")
            continue()
        endif()

        if(name MATCHES "^ak/")
            list(APPEND violations
                "${file}: forbidden include <${name}> (non-Planner Agent Kernel header)")
            continue()
        endif()

        if(name MATCHES "^runtime" OR name MATCHES "^capability_"
           OR name MATCHES "^event_bus" OR name MATCHES "^i_capability"
           OR name MATCHES "^scheduler" OR name MATCHES "^executor"
           OR name MATCHES "^session" OR name MATCHES "^workflow"
           OR name MATCHES "^task")
            list(APPEND violations
                "${file}: forbidden Runtime/subsystem include <${name}> (Runtime boundary violation)")
            continue()
        endif()

        if(name MATCHES "/")
            list(APPEND violations
                "${file}: unexpected non-standard include <${name}>")
        endif()
    endforeach()
endforeach()

# ------------------------------------------------------------
# 1b. Manager-style / universal type scan
# ------------------------------------------------------------
set(forbidden_name_fragments
    "Manager"
    "GlobalLifecycle"
    "UniversalCoordinator")

foreach(file IN LISTS planner_headers)
    file(READ "${file}" content)
    string(REGEX MATCHALL "(^|\n|[ \t])(class|struct|enum class)[ \t]+[A-Za-z_][A-Za-z0-9_]*" declarations "${content}")
    foreach(declaration IN LISTS declarations)
        string(REGEX MATCH "[A-Za-z_][A-Za-z0-9_]*$" type_name "${declaration}")
        foreach(fragment IN LISTS forbidden_name_fragments)
            if(type_name MATCHES "${fragment}")
                list(APPEND violations
                    "${file}: declared type '${type_name}' contains forbidden fragment '${fragment}'")
            endif()
        endforeach()
    endforeach()
endforeach()

# ------------------------------------------------------------
# 2. Link-boundary check
# ------------------------------------------------------------
# The Planner target SHALL link only agent_kernel_foundation.
if(NOT DEFINED PLANNER_LINK_LIBS OR NOT PLANNER_LINK_LIBS STREQUAL "agent_kernel_foundation")
    list(APPEND violations
        "agent_kernel_planner links against: ${PLANNER_LINK_LIBS}")
endif()

if(DEFINED PLANNER_INTERFACE_LINK_LIBS AND NOT PLANNER_INTERFACE_LINK_LIBS STREQUAL "agent_kernel_foundation")
    list(APPEND violations
        "agent_kernel_planner interface-links against: ${PLANNER_INTERFACE_LINK_LIBS}")
endif()

# ------------------------------------------------------------
# 3. Result
# ------------------------------------------------------------
list(LENGTH all_files all_files_count)
if(violations)
    foreach(violation IN LISTS violations)
        message(STATUS "PLANNER BOUNDARY VIOLATION: ${violation}")
    endforeach()
    message(FATAL_ERROR "P1-IS005 Planner boundary check failed")
endif()

message(STATUS "P1-IS005 Planner boundary check passed "
               "(${all_files_count} files, no forbidden dependencies)")
