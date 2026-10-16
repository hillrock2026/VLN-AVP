# ============================================================
# check_model_to_runtime_boundaries.cmake - TASK 3.4
# static boundary verification (TASK 3.4 Contract section 8;
# Implementation Plan section 15.3)
# ============================================================
# Verifies:
#   1. agent_kernel_model_to_runtime links ONLY:
#        agent_kernel_runtime_backed_agent
#        agent_kernel_agent_model
#        agent_kernel_agent_prompt
#        agent_kernel_context
#        agent_kernel_foundation
#      and does NOT link agent_kernel_runtime directly or
#      through its interface.
#   2. The module headers/sources contain no Runtime include:
#      no <runtime.h>, no Scheduler / Executor /
#      CapabilityResolver / EventBus types, no quoted includes
#      escaping the module.
#   3. Model boundary preserved: the module's Model-touching
#      code never calls Tool / Context / Agent-lifecycle /
#      Runtime APIs (include scan + link scan).
#   4. No test header is included in production code.
# ============================================================

cmake_policy(SET CMP0057 NEW)

set(violations "")

set(ALLOWED_LINKS
    agent_kernel_runtime_backed_agent
    agent_kernel_agent_model
    agent_kernel_agent_prompt
    agent_kernel_context
    agent_kernel_foundation
)

# ------------------------------------------------------------
# 1. Link boundary
# ------------------------------------------------------------
foreach(link_var IN ITEMS MRT_LINK_LIBS MRT_INTERFACE_LINK_LIBS)
    if(DEFINED ${link_var})
        set(value "${${link_var}}")
        string(REPLACE "$<LINK_ONLY:" "" value "${value}")
        string(REPLACE ">" " " value "${value}")
        string(REPLACE ";" " " value "${value}")
        separate_arguments(value)
        foreach(token IN LISTS value)
            if(NOT token)
                continue()
            endif()
            if(token STREQUAL "agent_kernel_runtime")
                list(APPEND violations
                    "${link_var} links a Runtime target: ${${link_var}}")
            elseif(NOT (token IN_LIST ALLOWED_LINKS))
                list(APPEND violations
                    "${link_var} links an unsanctioned target: ${token}")
            endif()
        endforeach()
    endif()
endforeach()

# ------------------------------------------------------------
# 2./3./4. Include-boundary scan
# ------------------------------------------------------------
if(NOT DEFINED MRT_INCLUDE_DIR OR NOT DEFINED MRT_SOURCE_DIR)
    message(FATAL_ERROR "MRT boundary-check directories are required")
endif()

file(GLOB_RECURSE module_headers "${MRT_INCLUDE_DIR}/*.hpp")
file(GLOB_RECURSE module_sources "${MRT_SOURCE_DIR}/*.cpp")

if(NOT module_headers)
    message(FATAL_ERROR "No module headers found under ${MRT_INCLUDE_DIR}")
endif()

set(scan_files ${module_headers} ${module_sources})

# Sanctioned include prefixes for the Agent-owned integration
# module (TASK 3.4 Contract sections 5-8; Plan section 15).
set(ALLOWED_INCLUDES
    "^agent_kernel/model_to_runtime/"
    "^agent_kernel/agent_prompt/"
    "^agent_kernel/agent_model/"
    "^agent_kernel/prompt/"
    "^agent_kernel/model/"
    "^agent_kernel/fwa/model_action\\.hpp"
    "^agent_kernel/tool/tool_identity\\.hpp"
    "^agent_kernel/runtime_backed_agent/"
    "^agent_kernel/foundation/"
)

foreach(file IN LISTS scan_files)
    file(READ "${file}" content)
    string(REGEX MATCHALL "#include[ \t]*[<\"][^>\"]+[>\"]" include_tokens "${content}")
    foreach(token IN LISTS include_tokens)
        string(REGEX REPLACE "^#include[ \t]*[<\"]" "" name "${token}")
        string(REGEX REPLACE "[>\"]$" "" name "${name}")

        # Quoted includes are forbidden (no local include bypass).
        if(token MATCHES "^#include[ \t]*\"")
            list(APPEND violations
                "${file}: forbidden quoted include \"${name}\"")
            continue()
        endif()

        # Runtime / Scheduler / Executor / CapabilityResolver /
        # EventBus / Runtime-internal includes are forbidden.
        if(name MATCHES "^agent_kernel/runtime/" OR name MATCHES "^runtime"
           OR name MATCHES "^agent_kernel/executor" OR name MATCHES "^agent_kernel/scheduler"
           OR name MATCHES "^agent_kernel/capability" OR name MATCHES "^agent_kernel/workflow"
           OR name MATCHES "^agent_kernel/task" OR name MATCHES "^capability_"
           OR name MATCHES "^event_bus" OR name MATCHES "^runtime_"
           OR name MATCHES "^i_capability" OR name MATCHES "^session"
           OR name MATCHES "^scheduler" OR name MATCHES "^executor")
            list(APPEND violations
                "${file}: forbidden Runtime include <${name}>")
            continue()
        endif()

        # Model boundary preserved: the module never includes
        # Tool (beyond the ModelAction identity value), Context,
        # Memory, Planner, Agent lifecycle, or Agent execution
        # internals directly. Context and Runtime interaction are
        # owned by the CLOSED TASK 3.3 composition.
        set(allowed FALSE)
        foreach(prefix IN LISTS ALLOWED_INCLUDES)
            if(name MATCHES "${prefix}")
                set(allowed TRUE)
                break()
            endif()
        endforeach()
        if(allowed)
            continue()
        endif()
        if(name MATCHES "^agent_kernel/")
            list(APPEND violations
                "${file}: forbidden boundary include <${name}>")
            continue()
        endif()

        # No test header in production code.
        if(name MATCHES "deterministic_model" OR name MATCHES "gtest"
           OR name MATCHES "gmock" OR name MATCHES "_test")
            list(APPEND violations
                "${file}: forbidden test include <${name}>")
            continue()
        endif()

        # Model-provider SDKs and ROS2 (Contract section 10.2).
        if(name MATCHES "openai" OR name MATCHES "deepseek"
           OR name MATCHES "qwen" OR name MATCHES "anthropic"
           OR name MATCHES "gemini" OR name MATCHES "transformers"
           OR name MATCHES "vllm" OR name MATCHES "llama"
           OR name MATCHES "rclcpp" OR name MATCHES "rcl/")
            list(APPEND violations
                "${file}: forbidden Model-provider/ROS2 include <${name}>")
            continue()
        endif()

        # Anything else with a path is an unexpected non-standard
        # include (standard headers carry no path).
        if(name MATCHES "/")
            list(APPEND violations
                "${file}: unexpected non-standard include <${name}>")
        endif()
    endforeach()
endforeach()

# ------------------------------------------------------------
# 5. Result
# ------------------------------------------------------------
list(LENGTH scan_files scan_count)
if(violations)
    foreach(violation IN LISTS violations)
        message(STATUS "MODEL-TO-RUNTIME BOUNDARY VIOLATION: ${violation}")
    endforeach()
    message(FATAL_ERROR "TASK 3.4 Model-to-Runtime boundary check failed")
endif()

message(STATUS "Model-to-Runtime boundary check passed "
               "(${scan_count} files, no forbidden dependencies)")