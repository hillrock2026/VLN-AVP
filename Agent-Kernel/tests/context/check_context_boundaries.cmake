# ============================================================
# check_context_boundaries.cmake - P1-IS004 static boundary check
# ============================================================
# Verifies, without requiring a behavioral test:
#
#  1. Every Context header and source is scanned.
#  2. No Runtime internal/public header, no Scheduler, Executor,
#     Capability Resolver, Event Bus, Workflow, Task, or Session
#     usage exists in the Context boundary.
#  3. No Agent/Memory/Planner/Tool internal include exists.
#  4. No Runtime adapter/binding surface exists.
#  5. No Manager-style universal type (ContextManager,
#     GlobalLifecycleManager, UniversalCoordinator, ...) is
#     declared by the Context boundary.
#  6. The agent_kernel_context target links only
#     agent_kernel_foundation.
#
# Usage (registered as a CTest):
#   cmake -DCONTEXT_INCLUDE_DIR=<dir>
#         -DCONTEXT_SOURCE_DIR=<dir>
#         -DCONTEXT_LINK_LIBS=<target LINK_LIBRARIES>
#         -DCONTEXT_INTERFACE_LINK_LIBS=<target INTERFACE_LINK_LIBRARIES>
#         -P check_context_boundaries.cmake
# ============================================================

if(NOT DEFINED CONTEXT_INCLUDE_DIR OR NOT DEFINED CONTEXT_SOURCE_DIR)
    message(FATAL_ERROR "CONTEXT_INCLUDE_DIR and CONTEXT_SOURCE_DIR are required")
endif()

set(violations "")

# ------------------------------------------------------------
# 1. Include-boundary scan (all headers and sources)
# ------------------------------------------------------------
file(GLOB_RECURSE context_headers
    "${CONTEXT_INCLUDE_DIR}/*.hpp")
file(GLOB context_sources
    "${CONTEXT_SOURCE_DIR}/*.cpp")

if(NOT context_headers)
    message(FATAL_ERROR "No Context headers found under ${CONTEXT_INCLUDE_DIR}")
endif()
if(NOT context_sources)
    message(FATAL_ERROR "No Context sources found under ${CONTEXT_SOURCE_DIR}")
endif()

set(all_files ${context_headers} ${context_sources})

foreach(file IN LISTS all_files)
    file(READ "${file}" content)
    string(REGEX MATCHALL "#include[ \t]*[<\"][^>\"]+[>\"]" include_tokens "${content}")
    foreach(token IN LISTS include_tokens)
        string(REGEX REPLACE "^#include[ \t]*[<\"]" "" name "${token}")
        string(REGEX REPLACE "[>\"]$" "" name "${name}")

        # Quoted includes are not used by the Context surface.
        if(token MATCHES "^#include[ \t]*\"")
            list(APPEND violations
                "${file}: quoted include \"${name}\" is not part of the Context boundary")
            continue()
        endif()

        # Allowed: standard library headers, the Context boundary,
        # and the Kernel Foundation.
        if(name MATCHES "^agent_kernel/context/")
            continue()
        endif()
        if(name MATCHES "^agent_kernel/foundation/")
            continue()
        endif()

        if(name MATCHES "^agent_kernel/")
            list(APPEND violations
                "${file}: forbidden subsystem/include <${name}> (Agent/Memory/Planner/Tool/Runtime boundary violation)")
            continue()
        endif()

        if(name MATCHES "^ak/")
            list(APPEND violations
                "${file}: forbidden include <${name}> (non-Context Agent Kernel header)")
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
# The Context boundary must not declare universal manager types
# or a universal coordinator (P1-IS004 Chapter 24.7).
set(forbidden_name_fragments
    "Manager"
    "GlobalLifecycle"
    "UniversalCoordinator")

foreach(file IN LISTS context_headers)
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
# The Context target SHALL link only agent_kernel_foundation.
if(NOT DEFINED CONTEXT_LINK_LIBS OR NOT CONTEXT_LINK_LIBS STREQUAL "agent_kernel_foundation")
    list(APPEND violations
        "agent_kernel_context links against: ${CONTEXT_LINK_LIBS}")
endif()

if(DEFINED CONTEXT_INTERFACE_LINK_LIBS AND NOT CONTEXT_INTERFACE_LINK_LIBS STREQUAL "agent_kernel_foundation")
    list(APPEND violations
        "agent_kernel_context interface-links against: ${CONTEXT_INTERFACE_LINK_LIBS}")
endif()

# ------------------------------------------------------------
# 3. Result
# ------------------------------------------------------------
list(LENGTH all_files all_files_count)
if(violations)
    foreach(violation IN LISTS violations)
        message(STATUS "CONTEXT BOUNDARY VIOLATION: ${violation}")
    endforeach()
    message(FATAL_ERROR "P1-IS004 Context boundary check failed")
endif()

message(STATUS "P1-IS004 Context boundary check passed "
               "(${all_files_count} files, no forbidden dependencies)")
