# ============================================================
# check_tool_boundaries.cmake - P1-IS006 Rev2 static boundary
# check (Tool boundary)
# ============================================================
# Verifies, without requiring a behavioral test:
#
#  1. Every Tool public header and implementation source is
#     scanned.
#  2. No Runtime internal/public header, no Scheduler,
#     Executor, Capability Resolver, Event Bus, Workflow, Task,
#     or Session usage exists in the Tool boundary (TOL-071).
#  3. No Agent/Context/Planner/Memory internal include exists.
#  4. No Runtime adapter/binding surface exists (TOL-072).
#  5. The prohibited public API names of Chapter 34 do not
#     appear on the Tool surface: ScheduleWork, ExecuteWork,
#     SubmitRuntimeRequest, ObserveRuntimeStatus,
#     TranslateRuntimeRequest, BindRuntimePublicApi,
#     ResolveRuntimeCapability, PublishRuntimeEvent,
#     RegisterTool, ListTools (TOL-074, TOL-081, TOL-083).
#  6. The agent_kernel_tool target links only
#     agent_kernel_foundation (TOL-073, TOL-102).
#
# Usage (registered as a CTest):
#   cmake -DTOOL_INCLUDE_DIR=<dir>
#         -DTOOL_SOURCE_DIR=<dir>
#         -DTOOL_LINK_LIBS=<target LINK_LIBRARIES>
#         -DTOOL_INTERFACE_LINK_LIBS=<target INTERFACE_LINK_LIBRARIES>
#         -P check_tool_boundaries.cmake
# ============================================================

if(NOT DEFINED TOOL_INCLUDE_DIR OR NOT DEFINED TOOL_SOURCE_DIR)
    message(FATAL_ERROR "TOOL_INCLUDE_DIR and TOOL_SOURCE_DIR are required")
endif()

set(violations "")

# ------------------------------------------------------------
# 1. Include-boundary scan (all headers and sources)
# ------------------------------------------------------------
file(GLOB_RECURSE tool_headers
    "${TOOL_INCLUDE_DIR}/*.hpp")
file(GLOB tool_sources
    "${TOOL_SOURCE_DIR}/*.cpp")

if(NOT tool_headers)
    message(FATAL_ERROR "No Tool headers found under ${TOOL_INCLUDE_DIR}")
endif()
if(NOT tool_sources)
    message(FATAL_ERROR "No Tool sources found under ${TOOL_SOURCE_DIR}")
endif()

set(all_files ${tool_headers} ${tool_sources})

foreach(file IN LISTS all_files)
    file(READ "${file}" content)
    string(REGEX MATCHALL "#include[ \t]*[<\"][^>\"]+[>\"]" include_tokens "${content}")
    foreach(token IN LISTS include_tokens)
        string(REGEX REPLACE "^#include[ \t]*[<\"]" "" name "${token}")
        string(REGEX REPLACE "[>\"]$" "" name "${name}")

        # Quoted includes are not used by the Tool surface.
        if(token MATCHES "^#include[ \t]*\"")
            list(APPEND violations
                "${file}: quoted include \"${name}\" is not part of the Tool boundary")
            continue()
        endif()

        # Allowed: standard library headers, the Tool boundary,
        # and the Kernel Foundation.
        if(name MATCHES "^agent_kernel/tool/")
            continue()
        endif()
        if(name MATCHES "^agent_kernel/foundation/")
            continue()
        endif()

        if(name MATCHES "^agent_kernel/")
            list(APPEND violations
                "${file}: forbidden subsystem/include <${name}> (Agent/Context/Planner/Memory/Agent-Tool boundary violation)")
            continue()
        endif()

        if(name MATCHES "^ak/")
            list(APPEND violations
                "${file}: forbidden include <${name}> (non-Tool Agent Kernel header)")
            continue()
        endif()

        if(name MATCHES "^runtime" OR name MATCHES "^capability_"
           OR name MATCHES "^event_bus" OR name MATCHES "^i_capability"
           OR name MATCHES "^scheduler" OR name MATCHES "^executor"
           OR name MATCHES "^session" OR name MATCHES "^workflow"
           OR name MATCHES "^task")
            list(APPEND violations
                "${file}: forbidden Runtime/subsystem include <${name}> (Runtime boundary violation, TOL-071)")
            continue()
        endif()

        if(name MATCHES "/")
            list(APPEND violations
                "${file}: unexpected non-standard include <${name}>")
        endif()
    endforeach()
endforeach()

# ------------------------------------------------------------
# 1b. Prohibited public API surface scan (Chapter 34, TOL-074)
# ------------------------------------------------------------
set(forbidden_api_names
    "ScheduleWork"
    "ExecuteWork"
    "SubmitRuntimeRequest"
    "ObserveRuntimeStatus"
    "TranslateRuntimeRequest"
    "BindRuntimePublicApi"
    "ResolveRuntimeCapability"
    "PublishRuntimeEvent"
    "RegisterTool"
    "ListTools")

foreach(file IN LISTS tool_headers)
    file(READ "${file}" content)
    # Strip comments first: conformance documentation may name
    # prohibited identifiers, so the scan verifies the actual
    # public surface rather than documentation text.
    string(REGEX REPLACE [==[/\*[^*]*\*+([^/*][^*]*\*+)*/]==] "" content "${content}")
    string(REGEX REPLACE [==[//.*]==] "" content "${content}")
    foreach(name IN LISTS forbidden_api_names)
        if(content MATCHES "${name}")
            list(APPEND violations
                "${file}: prohibited public API name '${name}' (Chapter 34)")
        endif()
    endforeach()
endforeach()

# ------------------------------------------------------------
# 2. Link-boundary check (TOL-073, TOL-102)
# ------------------------------------------------------------
if(NOT DEFINED TOOL_LINK_LIBS OR NOT TOOL_LINK_LIBS STREQUAL "agent_kernel_foundation")
    list(APPEND violations
        "agent_kernel_tool links against: ${TOOL_LINK_LIBS}")
endif()

if(DEFINED TOOL_INTERFACE_LINK_LIBS AND NOT TOOL_INTERFACE_LINK_LIBS STREQUAL ""
   AND NOT TOOL_INTERFACE_LINK_LIBS STREQUAL "agent_kernel_foundation")
    list(APPEND violations
        "agent_kernel_tool interface-links against: ${TOOL_INTERFACE_LINK_LIBS}")
endif()

# ------------------------------------------------------------
# 3. Result
# ------------------------------------------------------------
list(LENGTH all_files all_files_count)
if(violations)
    foreach(violation IN LISTS violations)
        message(STATUS "TOOL BOUNDARY VIOLATION: ${violation}")
    endforeach()
    message(FATAL_ERROR "P1-IS006 Rev2 Tool boundary check failed")
endif()

message(STATUS "P1-IS006 Rev2 Tool boundary check passed "
               "(${all_files_count} files, no forbidden dependencies)")