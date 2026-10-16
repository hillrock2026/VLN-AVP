# ============================================================
# check_agent_boundaries.cmake - P1-IS002 static boundary check
# ============================================================
# Verifies, without requiring a behavioral test:
#
#  1. Agent headers and sources include no Runtime internals
#     (scheduler/executor/capability/event bus/lifecycle), no
#     Runtime Public API binding, and no Memory/Context/Planner/
#     Tool internals.
#  2. Agent sources use only angle-bracket includes.
#  3. The agent_kernel_agent build target links only the Kernel
#     Foundation (no Runtime target, no reverse dependency).
#  4. The Agent boundary declares no Manager-style universal
#     types (MemoryManager, PlannerManager, ToolManager,
#     ContextManager, RuntimeManager, GlobalLifecycleManager,
#     UniversalKernelCoordinator).
#
# Usage (registered as a CTest):
#   cmake -DAGENT_INCLUDE_DIR=<dir>
#         -DAGENT_SOURCE_DIR=<dir>
#         -DAGENT_LINK_LIBS=<target LINK_LIBRARIES>
#         -DAGENT_INTERFACE_LINK_LIBS=<target INTERFACE_LINK_LIBRARIES>
#         -P check_agent_boundaries.cmake
# ============================================================

if(NOT DEFINED AGENT_INCLUDE_DIR OR NOT DEFINED AGENT_SOURCE_DIR)
    message(FATAL_ERROR "AGENT_INCLUDE_DIR and AGENT_SOURCE_DIR are required")
endif()

set(violations "")

# ------------------------------------------------------------
# 1. Include-boundary scan
# ------------------------------------------------------------
file(GLOB_RECURSE agent_headers
    "${AGENT_INCLUDE_DIR}/*.hpp")
file(GLOB agent_sources
    "${AGENT_SOURCE_DIR}/*.cpp")

if(NOT agent_headers)
    message(FATAL_ERROR "No Agent headers found under ${AGENT_INCLUDE_DIR}")
endif()

set(all_files ${agent_headers} ${agent_sources})

foreach(file IN LISTS all_files)
    file(READ "${file}" content)
    string(REGEX MATCHALL "#include[ \t]*[<\"][^>\"]+[>\"]" include_tokens "${content}")
    foreach(token IN LISTS include_tokens)
        string(REGEX REPLACE "^#include[ \t]*[<\"]" "" name "${token}")
        string(REGEX REPLACE "[>\"]$" "" name "${name}")

        # Quoted includes are not used by the Agent surface.
        if(token MATCHES "^#include[ \t]*\"")
            list(APPEND violations
                "${file}: quoted include \"${name}\" is not part of the Agent boundary")
            continue()
        endif()

        # Allowed: standard library headers, the Agent boundary,
        # and the Kernel Foundation.
        if(name MATCHES "^agent_kernel/agent/")
            continue()
        endif()
        if(name MATCHES "^agent_kernel/foundation/")
            continue()
        endif()

        if(name MATCHES "^agent_kernel/")
            list(APPEND violations
                "${file}: forbidden subsystem/include <${name}> (reverse or out-of-boundary dependency)")
            continue()
        endif()

        if(name MATCHES "^ak/")
            list(APPEND violations
                "${file}: forbidden include <${name}> (non-Agent Agent Kernel header)")
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
# The Agent boundary must not declare universal manager types
# (P1-IS002 Chapter 17.3) or a universal coordinator.
set(forbidden_name_fragments
    "Manager"
    "GlobalLifecycle"
    "UniversalKernelCoordinator")

foreach(file IN LISTS agent_headers)
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
# The Agent target SHALL link only agent_kernel_foundation.
if(NOT DEFINED AGENT_LINK_LIBS OR NOT AGENT_LINK_LIBS STREQUAL "agent_kernel_foundation")
    list(APPEND violations
        "agent_kernel_agent links against: ${AGENT_LINK_LIBS}")
endif()

if(DEFINED AGENT_INTERFACE_LINK_LIBS AND NOT AGENT_INTERFACE_LINK_LIBS STREQUAL "agent_kernel_foundation")
    list(APPEND violations
        "agent_kernel_agent interface-links against: ${AGENT_INTERFACE_LINK_LIBS}")
endif()

# ------------------------------------------------------------
# 3. Result
# ------------------------------------------------------------
list(LENGTH all_files all_files_count)
if(violations)
    foreach(violation IN LISTS violations)
        message(STATUS "AGENT BOUNDARY VIOLATION: ${violation}")
    endforeach()
    message(FATAL_ERROR "P1-IS002 Agent boundary check failed")
endif()

message(STATUS "P1-IS002 Agent boundary check passed "
               "(${all_files_count} files, no forbidden dependencies)")
