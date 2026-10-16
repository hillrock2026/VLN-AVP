# ============================================================
# check_foundation_boundaries.cmake - P1-IS001 static check
# ============================================================
# Verifies, without requiring a behavioral test:
#
#  1. Foundation headers and sources include no Agent, Memory,
#     Context, Planner, Tool, Execution Composition, Runtime
#     Adapter, or Runtime internal/public headers.
#  2. Foundation sources use only angle-bracket includes.
#  3. The agent_kernel_foundation build target links against
#     nothing (no reverse dependency, no Runtime dependency).
#
# Usage (registered as a CTest):
#   cmake -DFOUNDATION_INCLUDE_DIR=<dir>
#         -DFOUNDATION_SOURCE_DIR=<dir>
#         -DFOUNDATION_LINK_LIBS=<target LINK_LIBRARIES>
#         -DFOUNDATION_INTERFACE_LINK_LIBS=<target INTERFACE_LINK_LIBRARIES>
#         -P check_foundation_boundaries.cmake
# ============================================================

if(NOT DEFINED FOUNDATION_INCLUDE_DIR OR NOT DEFINED FOUNDATION_SOURCE_DIR)
    message(FATAL_ERROR "FOUNDATION_INCLUDE_DIR and FOUNDATION_SOURCE_DIR are required")
endif()

set(violations "")

# ------------------------------------------------------------
# 1. Include-boundary scan
# ------------------------------------------------------------
file(GLOB_RECURSE foundation_headers
    "${FOUNDATION_INCLUDE_DIR}/*.hpp")
file(GLOB foundation_sources
    "${FOUNDATION_SOURCE_DIR}/*.cpp")

if(NOT foundation_headers)
    message(FATAL_ERROR "No Foundation headers found under ${FOUNDATION_INCLUDE_DIR}")
endif()

set(all_files ${foundation_headers} ${foundation_sources})

foreach(file IN LISTS all_files)
    file(READ "${file}" content)
    string(REGEX MATCHALL "#include[ \t]*[<\"][^>\"]+[>\"]" include_tokens "${content}")
    foreach(token IN LISTS include_tokens)
        string(REGEX REPLACE "^#include[ \t]*[<\"]" "" name "${token}")
        string(REGEX REPLACE "[>\"]$" "" name "${name}")

        if(name STREQUAL token)
            message(FATAL_ERROR "Could not parse include token in ${file}: ${token}")
        endif()

        # Quoted includes are not used by the Foundation surface.
        if(token MATCHES "^#include[ \t]*\"")
            list(APPEND violations
                "${file}: quoted include \"${name}\" is not part of the neutral Foundation surface")
            continue()
        endif()

        # Allowed: standard library headers and the Foundation boundary itself.
        if(name MATCHES "^agent_kernel/foundation/")
            continue()
        endif()

        if(name MATCHES "^agent_kernel/")
            list(APPEND violations
                "${file}: forbidden subsystem include <${name}> (reverse dependency)")
            continue()
        endif()

        if(name MATCHES "^ak/")
            list(APPEND violations
                "${file}: forbidden include <${name}> (non-Foundation Agent Kernel header)")
            continue()
        endif()

        if(name MATCHES "^runtime" OR name MATCHES "^capability_"
           OR name MATCHES "^event_bus" OR name MATCHES "^i_capability")
            list(APPEND violations
                "${file}: forbidden Runtime include <${name}> (Runtime boundary violation)")
            continue()
        endif()

        if(name MATCHES "/")
            list(APPEND violations
                "${file}: unexpected non-standard include <${name}>")
        endif()
    endforeach()
endforeach()

# ------------------------------------------------------------
# 1b. Declared-type-name scan
# ------------------------------------------------------------
# Foundation public contracts must not define types that mimic
# Runtime or subsystem surfaces (e.g. no RuntimeEvent,
# EventBus, CapabilityResolver, RuntimeScheduler).
set(forbidden_name_fragments
    "Runtime"
    "EventBus"
    "Capability"
    "Scheduler"
    "Executor"
    "Resolver"
    "Adapter")

foreach(file IN LISTS foundation_headers)
    file(READ "${file}" content)
    string(REGEX MATCHALL "(^|\n|[ \t])(class|struct|enum class|enum)[ \t]+[A-Za-z_][A-Za-z0-9_]*" declarations "${content}")
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
if(DEFINED FOUNDATION_LINK_LIBS AND NOT FOUNDATION_LINK_LIBS STREQUAL "")
    list(APPEND violations
        "agent_kernel_foundation links against: ${FOUNDATION_LINK_LIBS}")
endif()

if(DEFINED FOUNDATION_INTERFACE_LINK_LIBS AND NOT FOUNDATION_INTERFACE_LINK_LIBS STREQUAL "")
    list(APPEND violations
        "agent_kernel_foundation interface-links against: ${FOUNDATION_INTERFACE_LINK_LIBS}")
endif()

# ------------------------------------------------------------
# 3. Result
# ------------------------------------------------------------
list(LENGTH all_files all_files_count)
if(violations)
    foreach(violation IN LISTS violations)
        message(STATUS "FOUNDATION BOUNDARY VIOLATION: ${violation}")
    endforeach()
    message(FATAL_ERROR "P1-IS001 Foundation boundary check failed")
endif()

message(STATUS "P1-IS001 Foundation boundary check passed "
               "(${all_files_count} files, no forbidden dependencies)")