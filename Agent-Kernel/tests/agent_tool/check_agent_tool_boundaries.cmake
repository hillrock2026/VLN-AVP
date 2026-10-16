# ============================================================
# check_agent_tool_boundaries.cmake - P1-IS006 Rev2 static
# boundary check (Agent-Tool boundary)
# ============================================================
# Verifies, without requiring a behavioral test:
#
#  1. Every AgentTool public header and implementation source
#     is scanned.
#  2. No Runtime internal/public header, no Scheduler,
#     Executor, Capability Resolver, Event Bus, Workflow, Task,
#     or Session usage exists in the boundary.
#  3. No Agent/Context/Planner/Memory internal include exists
#     (only agent_kernel/tool, agent_kernel/foundation and
#     agent_kernel/agent_tool are permitted).
#  4. The prohibited public API names of Chapter 34 do not
#     appear: ScheduleWork, ExecuteWork, SubmitRuntimeRequest,
#     ObserveRuntimeStatus, TranslateRuntimeRequest,
#     BindRuntimePublicApi, ResolveRuntimeCapability,
#     PublishRuntimeEvent, RegisterTool, ListTools (TOL-074).
#  5. AgentToolHost exposes no public Tool() accessor
#     (TOL-084): the literal "Tool()" must not appear in
#     agent_tool_host.hpp.
#  6. The agent_kernel_agent_tool target links only
#     agent_kernel_tool + agent_kernel_foundation (TOL-102).
#
# Usage (registered as a CTest):
#   cmake -DAGENT_TOOL_INCLUDE_DIR=<dir>
#         -DAGENT_TOOL_SOURCE_DIR=<dir>
#         -DAGENT_TOOL_LINK_LIBS=<target LINK_LIBRARIES>
#         -DAGENT_TOOL_INTERFACE_LINK_LIBS=<target INTERFACE_LINK_LIBRARIES>
#         -P check_agent_tool_boundaries.cmake
# ============================================================

if(NOT DEFINED AGENT_TOOL_INCLUDE_DIR OR NOT DEFINED AGENT_TOOL_SOURCE_DIR)
    message(FATAL_ERROR "AGENT_TOOL_INCLUDE_DIR and AGENT_TOOL_SOURCE_DIR are required")
endif()

set(violations "")

# ------------------------------------------------------------
# 1. Include-boundary scan (all headers and sources)
# ------------------------------------------------------------
file(GLOB_RECURSE agent_tool_headers
    "${AGENT_TOOL_INCLUDE_DIR}/*.hpp")
file(GLOB agent_tool_sources
    "${AGENT_TOOL_SOURCE_DIR}/*.cpp")

if(NOT agent_tool_headers)
    message(FATAL_ERROR "No AgentTool headers found under ${AGENT_TOOL_INCLUDE_DIR}")
endif()
if(NOT agent_tool_sources)
    message(FATAL_ERROR "No AgentTool sources found under ${AGENT_TOOL_SOURCE_DIR}")
endif()

set(all_files ${agent_tool_headers} ${agent_tool_sources})

foreach(file IN LISTS all_files)
    file(READ "${file}" content)
    string(REGEX MATCHALL "#include[ \t]*[<\"][^>\"]+[>\"]" include_tokens "${content}")
    foreach(token IN LISTS include_tokens)
        string(REGEX REPLACE "^#include[ \t]*[<\"]" "" name "${token}")
        string(REGEX REPLACE "[>\"]$" "" name "${name}")

        if(token MATCHES "^#include[ \t]*\"")
            list(APPEND violations
                "${file}: quoted include \"${name}\" is not part of the AgentTool boundary")
            continue()
        endif()

        # Allowed: standard library headers, the Tool boundary,
        # the Kernel Foundation, and this boundary itself.
        if(name MATCHES "^agent_kernel/agent_tool/")
            continue()
        endif()
        if(name MATCHES "^agent_kernel/tool/")
            continue()
        endif()
        if(name MATCHES "^agent_kernel/foundation/")
            continue()
        endif()

        if(name MATCHES "^agent_kernel/")
            list(APPEND violations
                "${file}: forbidden subsystem/include <${name}> (Agent/Context/Planner/Memory boundary violation)")
            continue()
        endif()

        if(name MATCHES "^ak/")
            list(APPEND violations
                "${file}: forbidden include <${name}> (non-AgentTool Agent Kernel header)")
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

foreach(file IN LISTS agent_tool_headers)
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
# 1c. No public Tool() accessor on AgentToolHost (TOL-084)
# ------------------------------------------------------------
set(host_file "${AGENT_TOOL_INCLUDE_DIR}/agent_tool_host.hpp")
if(EXISTS "${host_file}")
    file(READ "${host_file}" host_content)
    # Ignore comments: the header documents the absence of a
    # public Tool() accessor (TOL-084) without declaring one.
    string(REGEX REPLACE [==[/\*[^*]*\*+([^/*][^*]*\*+)*/]==] "" host_content "${host_content}")
    string(REGEX REPLACE [==[//.*]==] "" host_content "${host_content}")
    if(host_content MATCHES "Tool\\(")
        list(APPEND violations
            "${host_file}: prohibited public Tool() accessor (TOL-084)")
    endif()
endif()

# ------------------------------------------------------------
# 2. Link-boundary check (TOL-102)
# ------------------------------------------------------------
set(expected_links "agent_kernel_tool;agent_kernel_foundation")
if(NOT DEFINED AGENT_TOOL_LINK_LIBS OR NOT AGENT_TOOL_LINK_LIBS STREQUAL "${expected_links}")
    list(APPEND violations
        "agent_kernel_agent_tool links against: ${AGENT_TOOL_LINK_LIBS}")
endif()

if(DEFINED AGENT_TOOL_INTERFACE_LINK_LIBS AND NOT AGENT_TOOL_INTERFACE_LINK_LIBS STREQUAL ""
   AND NOT AGENT_TOOL_INTERFACE_LINK_LIBS STREQUAL "${expected_links}")
    list(APPEND violations
        "agent_kernel_agent_tool interface-links against: ${AGENT_TOOL_INTERFACE_LINK_LIBS}")
endif()

# ------------------------------------------------------------
# 3. Result
# ------------------------------------------------------------
list(LENGTH all_files all_files_count)
if(violations)
    foreach(violation IN LISTS violations)
        message(STATUS "AGENT TOOL BOUNDARY VIOLATION: ${violation}")
    endforeach()
    message(FATAL_ERROR "P1-IS006 Rev2 Agent-Tool boundary check failed")
endif()

message(STATUS "P1-IS006 Rev2 Agent-Tool boundary check passed "
               "(${all_files_count} files, no forbidden dependencies)")