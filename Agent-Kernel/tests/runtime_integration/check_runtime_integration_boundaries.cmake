# ============================================================
# check_runtime_integration_boundaries.cmake - TASK 3.1 §20/§21
# static boundary verification (CC-8; T3.2-AC-005/016)
# ============================================================
# Verifies:
#   1. The Agent subsystem (agent_kernel_agent) and the First
#      Working Agent composition (agent_kernel_first_working_agent)
#      never link a Runtime target.
#   2. Tool / Planner / Model / Context / Memory / Prompt
#      production targets never link a Runtime target.
#   3. The integration adapter (agent_kernel_runtime_integration)
#      links the Runtime (the sanctioned sole production Runtime
#      link) and exposes no Runtime include through its public
#      header.
#   4. Agent headers, FWA headers, and the adapter public header
#      contain no Runtime include; only the adapter translation
#      unit may include the Runtime Public API.
# ============================================================

set(violations "")

# ------------------------------------------------------------
# 1/2. Production targets stay Runtime-free
# ------------------------------------------------------------
set(production_link_vars
    "RI_AGENT_LINK_LIBS|agent_kernel_agent"
    "RI_AGENT_INTERFACE_LINK_LIBS|agent_kernel_agent (interface)"
    "RI_FWA_LINK_LIBS|agent_kernel_first_working_agent"
    "RI_FWA_INTERFACE_LINK_LIBS|agent_kernel_first_working_agent (interface)"
    "RI_TOOL_LINK_LIBS|agent_kernel_tool"
    "RI_PLANNER_LINK_LIBS|agent_kernel_planner"
    "RI_MODEL_LINK_LIBS|agent_kernel_model"
    "RI_CONTEXT_LINK_LIBS|agent_kernel_context"
    "RI_MEMORY_LINK_LIBS|agent_kernel_memory"
    "RI_PROMPT_LINK_LIBS|agent_kernel_prompt")

foreach(entry IN LISTS production_link_vars)
    string(REPLACE "|" ";" parts "${entry}")
    list(GET parts 0 var_name)
    list(GET parts 1 label)
    if(DEFINED ${var_name})
        set(value "${${var_name}}")
        if(value MATCHES "runtime")
            list(APPEND violations
                "${label} links a Runtime target: ${value}")
        endif()
    endif()
endforeach()

# ------------------------------------------------------------
# 3. The integration adapter is the sole production Runtime link
# ------------------------------------------------------------
if(DEFINED RI_INTEGRATION_LINK_LIBS AND NOT RI_INTEGRATION_LINK_LIBS MATCHES "agent_kernel_runtime")
    list(APPEND violations
        "agent_kernel_runtime_integration does not link agent_kernel_runtime: ${RI_INTEGRATION_LINK_LIBS}")
endif()

# ------------------------------------------------------------
# 4. Include-boundary scan
# ------------------------------------------------------------
if(NOT DEFINED RI_AGENT_INCLUDE_DIR OR NOT DEFINED RI_FWA_INCLUDE_DIR
   OR NOT DEFINED RI_ADAPTER_INCLUDE_DIR OR NOT DEFINED RI_ADAPTER_SOURCE_DIR)
    message(FATAL_ERROR "RI boundary-check directories are required")
endif()

file(GLOB_RECURSE agent_headers "${RI_AGENT_INCLUDE_DIR}/*.hpp")
file(GLOB fwa_headers "${RI_FWA_INCLUDE_DIR}/*.hpp")
file(GLOB adapter_headers "${RI_ADAPTER_INCLUDE_DIR}/*.hpp")
file(GLOB adapter_sources "${RI_ADAPTER_SOURCE_DIR}/*.cpp")

if(NOT agent_headers)
    message(FATAL_ERROR "No Agent headers found under ${RI_AGENT_INCLUDE_DIR}")
endif()

set(scan_files ${agent_headers} ${fwa_headers} ${adapter_headers} ${adapter_sources})

foreach(file IN LISTS scan_files)
    file(READ "${file}" content)
    string(REGEX MATCHALL "#include[ \t]*[<\"][^>\"]+[>\"]" include_tokens "${content}")
    foreach(token IN LISTS include_tokens)
        string(REGEX REPLACE "^#include[ \t]*[<\"]" "" name "${token}")
        string(REGEX REPLACE "[>\"]$" "" name "${name}")

        if(name MATCHES "^agent_kernel/runtime/" OR name MATCHES "^runtime"
           OR name MATCHES "^agent_kernel/executor" OR name MATCHES "^agent_kernel/scheduler"
           OR name MATCHES "^agent_kernel/capability" OR name MATCHES "^agent_kernel/workflow"
           OR name MATCHES "^agent_kernel/task" OR name MATCHES "^capability_"
           OR name MATCHES "^event_bus" OR name MATCHES "^runtime_")
            # Only the adapter translation unit is the sanctioned
            # point that may include the Runtime Public API.
            if(NOT file MATCHES "runtime_public_api_adapter\\.cpp$")
                list(APPEND violations
                    "${file}: forbidden Runtime include <${name}>")
            endif()
        endif()
    endforeach()
endforeach()

# ------------------------------------------------------------
# 5. Result
# ------------------------------------------------------------
if(violations)
    foreach(violation IN LISTS violations)
        message(STATUS "RUNTIME INTEGRATION BOUNDARY VIOLATION: ${violation}")
    endforeach()
    message(FATAL_ERROR "Runtime integration boundary check failed")
endif()

message(STATUS "Runtime integration boundary check passed")