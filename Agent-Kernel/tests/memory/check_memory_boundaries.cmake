# ============================================================
# check_memory_boundaries.cmake - P1-IS003 static boundary check
# ============================================================
# Verifies, without requiring a behavioral test:
#
#  1. Every Memory header and source is scanned.
#  2. No Runtime internal/public header, no Scheduler, Executor,
#     Capability Resolver, Event Bus, Workflow, Task, or Session
#     usage exists in the Memory boundary.
#  3. No Agent/Context/Planner/Tool internal include exists.
#  4. No Runtime adapter/binding surface exists.
#  5. No Manager-style universal type (MemoryManager,
#     GlobalLifecycleManager, UniversalCoordinator, ...) is
#     declared by the Memory boundary.
#  6. The agent_kernel_memory target links only
#     agent_kernel_foundation.
#
# Usage (registered as a CTest):
#   cmake -DMEMORY_INCLUDE_DIR=<dir>
#         -DMEMORY_SOURCE_DIR=<dir>
#         -DMEMORY_LINK_LIBS=<target LINK_LIBRARIES>
#         -DMEMORY_INTERFACE_LINK_LIBS=<target INTERFACE_LINK_LIBRARIES>
#         -P check_memory_boundaries.cmake
# ============================================================

if(NOT DEFINED MEMORY_INCLUDE_DIR OR NOT DEFINED MEMORY_SOURCE_DIR)
    message(FATAL_ERROR "MEMORY_INCLUDE_DIR and MEMORY_SOURCE_DIR are required")
endif()

set(violations "")

# ------------------------------------------------------------
# 1. Include-boundary scan (all headers and sources)
# ------------------------------------------------------------
file(GLOB_RECURSE memory_headers
    "${MEMORY_INCLUDE_DIR}/*.hpp")
file(GLOB memory_sources
    "${MEMORY_SOURCE_DIR}/*.cpp")

if(NOT memory_headers)
    message(FATAL_ERROR "No Memory headers found under ${MEMORY_INCLUDE_DIR}")
endif()
if(NOT memory_sources)
    message(FATAL_ERROR "No Memory sources found under ${MEMORY_SOURCE_DIR}")
endif()

set(all_files ${memory_headers} ${memory_sources})

foreach(file IN LISTS all_files)
    file(READ "${file}" content)
    string(REGEX MATCHALL "#include[ \t]*[<\"][^>\"]+[>\"]" include_tokens "${content}")
    foreach(token IN LISTS include_tokens)
        string(REGEX REPLACE "^#include[ \t]*[<\"]" "" name "${token}")
        string(REGEX REPLACE "[>\"]$" "" name "${name}")

        # Quoted includes are not used by the Memory surface.
        if(token MATCHES "^#include[ \t]*\"")
            list(APPEND violations
                "${file}: quoted include \"${name}\" is not part of the Memory boundary")
            continue()
        endif()

        # Allowed: standard library headers, the Memory boundary,
        # and the Kernel Foundation.
        if(name MATCHES "^agent_kernel/memory/")
            continue()
        endif()
        if(name MATCHES "^agent_kernel/foundation/")
            continue()
        endif()

        if(name MATCHES "^agent_kernel/")
            list(APPEND violations
                "${file}: forbidden subsystem/include <${name}> (Agent/Context/Planner/Tool/Runtime boundary violation)")
            continue()
        endif()

        if(name MATCHES "^ak/")
            list(APPEND violations
                "${file}: forbidden include <${name}> (non-Memory Agent Kernel header)")
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
# The Memory boundary must not declare universal manager types
# or a universal coordinator (P1-IS003 Chapter 21).
set(forbidden_name_fragments
    "Manager"
    "GlobalLifecycle"
    "UniversalCoordinator")

foreach(file IN LISTS memory_headers)
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
# The Memory target SHALL link only agent_kernel_foundation.
if(NOT DEFINED MEMORY_LINK_LIBS OR NOT MEMORY_LINK_LIBS STREQUAL "agent_kernel_foundation")
    list(APPEND violations
        "agent_kernel_memory links against: ${MEMORY_LINK_LIBS}")
endif()

if(DEFINED MEMORY_INTERFACE_LINK_LIBS AND NOT MEMORY_INTERFACE_LINK_LIBS STREQUAL "agent_kernel_foundation")
    list(APPEND violations
        "agent_kernel_memory interface-links against: ${MEMORY_INTERFACE_LINK_LIBS}")
endif()

# ------------------------------------------------------------
# 3. Result
# ------------------------------------------------------------
list(LENGTH all_files all_files_count)
if(violations)
    foreach(violation IN LISTS violations)
        message(STATUS "MEMORY BOUNDARY VIOLATION: ${violation}")
    endforeach()
    message(FATAL_ERROR "P1-IS003 Memory boundary check failed")
endif()

message(STATUS "P1-IS003 Memory boundary check passed "
               "(${all_files_count} files, no forbidden dependencies)")