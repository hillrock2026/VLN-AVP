# ============================================================
# check_agent_prompt_boundaries.cmake - P1-IS007 Rev1.1
# static boundary check (Agent-owned Prompt boundary)
# ============================================================
# Verifies, without requiring a behavioral test:
#
#  1. Every AgentPrompt public header and implementation source
#     is scanned.
#  2. Only standard headers, the AgentPrompt boundary, the
#     Prompt public contract, and the Kernel Foundation are
#     included (PRM-022, PRM-023, PRM-030).
#  3. No Runtime/Scheduler/Executor/CapabilityResolver/EventBus
#     include exists (PRM-008).
#  4. No Memory/Context/Planner/Tool implementation include
#     exists (PRM-024..PRM-027).
#  5. No concrete Model-provider SDK or ROS2 include exists
#     (PRM-029, TOL-027).
#  6. The prohibited public API names do not appear on the
#     AgentPrompt surface (no active retrieval, no lifecycle
#     authority, no second coordination API).
#  7. AgentPromptHost exposes no public Prompt() accessor
#     (Chapter 19.3, PRM-023).
#  8. The agent_kernel_agent_prompt target links only
#     agent_kernel_prompt + agent_kernel_foundation (PRM-030).
#
# Usage (registered as a CTest):
#   cmake -DAGENT_PROMPT_INCLUDE_DIR=<dir>
#         -DAGENT_PROMPT_SOURCE_DIR=<dir>
#         -DAGENT_PROMPT_LINK_LIBS=<target LINK_LIBRARIES>
#         -DAGENT_PROMPT_INTERFACE_LINK_LIBS=<target INTERFACE_LINK_LIBRARIES>
#         -P check_agent_prompt_boundaries.cmake
# ============================================================

if(NOT DEFINED AGENT_PROMPT_INCLUDE_DIR OR NOT DEFINED AGENT_PROMPT_SOURCE_DIR)
    message(FATAL_ERROR "AGENT_PROMPT_INCLUDE_DIR and AGENT_PROMPT_SOURCE_DIR are required")
endif()

set(violations "")

# ------------------------------------------------------------
# 1. Include-boundary scan (all headers and sources)
# ------------------------------------------------------------
file(GLOB_RECURSE agent_prompt_headers
    "${AGENT_PROMPT_INCLUDE_DIR}/*.hpp")
file(GLOB agent_prompt_sources
    "${AGENT_PROMPT_SOURCE_DIR}/*.cpp")

if(NOT agent_prompt_headers)
    message(FATAL_ERROR "No AgentPrompt headers found under ${AGENT_PROMPT_INCLUDE_DIR}")
endif()
if(NOT agent_prompt_sources)
    message(FATAL_ERROR "No AgentPrompt sources found under ${AGENT_PROMPT_SOURCE_DIR}")
endif()

set(all_files ${agent_prompt_headers} ${agent_prompt_sources})

foreach(file IN LISTS all_files)
    file(READ "${file}" content)
    string(REGEX MATCHALL "#include[ \t]*[<\"][^>\"]+[>\"]" include_tokens "${content}")
    foreach(token IN LISTS include_tokens)
        string(REGEX REPLACE "^#include[ \t]*[<\"]" "" name "${token}")
        string(REGEX REPLACE "[>\"]$" "" name "${name}")

        # Quoted includes are not used by the AgentPrompt
        # surface.
        if(token MATCHES "^#include[ \t]*\"")
            list(APPEND violations
                "${file}: quoted include \"${name}\" is not part of the AgentPrompt boundary")
            continue()
        endif()

        # Allowed: standard library headers, the AgentPrompt
        # boundary, the Prompt public contract, and the Kernel
        # Foundation.
        if(name MATCHES "^agent_kernel/agent_prompt/")
            continue()
        endif()
        if(name MATCHES "^agent_kernel/prompt/")
            continue()
        endif()
        if(name MATCHES "^agent_kernel/foundation/")
            continue()
        endif()

        if(name MATCHES "^agent_kernel/")
            list(APPEND violations
                "${file}: forbidden subsystem/include <${name}> (Agent/Context/Planner/Memory/Tool boundary violation)")
            continue()
        endif()

        if(name MATCHES "^ak/")
            list(APPEND violations
                "${file}: forbidden include <${name}> (non-AgentPrompt Agent Kernel header)")
            continue()
        endif()

        if(name MATCHES "^runtime" OR name MATCHES "^capability_"
           OR name MATCHES "^event_bus" OR name MATCHES "^i_capability"
           OR name MATCHES "^scheduler" OR name MATCHES "^executor"
           OR name MATCHES "^session" OR name MATCHES "^workflow"
           OR name MATCHES "^task")
            list(APPEND violations
                "${file}: forbidden Runtime/subsystem include <${name}> (Runtime boundary violation, PRM-008)")
            continue()
        endif()

        # Concrete Model-provider SDKs and ROS2 (PRM-029,
        # TOL-027).
        if(name MATCHES "openai" OR name MATCHES "deepseek"
           OR name MATCHES "qwen" OR name MATCHES "anthropic"
           OR name MATCHES "gemini" OR name MATCHES "transformers"
           OR name MATCHES "vllm" OR name MATCHES "llama"
           OR name MATCHES "rclcpp" OR name MATCHES "rcl/")
            list(APPEND violations
                "${file}: forbidden Model-provider/ROS2 include <${name}> (PRM-029, TOL-027)")
            continue()
        endif()

        if(name MATCHES "/")
            list(APPEND violations
                "${file}: unexpected non-standard include <${name}>")
        endif()
    endforeach()
endforeach()

# ------------------------------------------------------------
# 1b. Prohibited public API surface scan (PRM-036, PRM-048)
# ------------------------------------------------------------
set(forbidden_api_names
    "RetrieveMemory"
    "QueryMemory"
    "RetrieveContext"
    "QueryContext"
    "InvokePlanner"
    "QueryPlanner"
    "DiscoverTool"
    "ExecuteTool"
    "RegisterTool"
    "ListTools"
    "ScheduleWork"
    "ExecuteWork"
    "SubmitRuntimeRequest"
    "ObserveRuntimeStatus"
    "TranslateRuntimeRequest"
    "BindRuntimePublicApi"
    "ResolveRuntimeCapability"
    "PublishRuntimeEvent"
    "RegisterPrompt"
    "ListPrompts"
    "InitializePrompt"
    "TerminatePrompt")

foreach(file IN LISTS agent_prompt_headers)
    file(READ "${file}" content)
    string(REGEX REPLACE [==[/\*[^*]*\*+([^/*][^*]*\*+)*/]==] "" content "${content}")
    string(REGEX REPLACE [==[//.*]==] "" content "${content}")
    foreach(name IN LISTS forbidden_api_names)
        if(content MATCHES "${name}")
            list(APPEND violations
                "${file}: prohibited public API name '${name}' (PRM-036/PRM-048)")
        endif()
    endforeach()
endforeach()

# ------------------------------------------------------------
# 1c. No public Prompt() accessor on AgentPromptHost
#     (Chapter 19.3, PRM-023)
# ------------------------------------------------------------
set(host_file "${AGENT_PROMPT_INCLUDE_DIR}/agent_prompt_host.hpp")
if(EXISTS "${host_file}")
    file(READ "${host_file}" host_content)
    # Ignore comments: the header documents the absence of a
    # public Prompt() accessor without declaring one.
    string(REGEX REPLACE [==[/\*[^*]*\*+([^/*][^*]*\*+)*/]==] "" host_content "${host_content}")
    string(REGEX REPLACE [==[//.*]==] "" host_content "${host_content}")
    if(host_content MATCHES "Prompt\\(")
        list(APPEND violations
            "${host_file}: prohibited public Prompt() accessor (Chapter 19.3)")
    endif()
endif()

# ------------------------------------------------------------
# 2. Link-boundary check (PRM-030)
# ------------------------------------------------------------
set(expected_links "agent_kernel_prompt;agent_kernel_foundation")
if(NOT DEFINED AGENT_PROMPT_LINK_LIBS OR NOT AGENT_PROMPT_LINK_LIBS STREQUAL "${expected_links}")
    list(APPEND violations
        "agent_kernel_agent_prompt links against: ${AGENT_PROMPT_LINK_LIBS}")
endif()

if(DEFINED AGENT_PROMPT_INTERFACE_LINK_LIBS AND NOT AGENT_PROMPT_INTERFACE_LINK_LIBS STREQUAL ""
   AND NOT AGENT_PROMPT_INTERFACE_LINK_LIBS STREQUAL "${expected_links}")
    list(APPEND violations
        "agent_kernel_agent_prompt interface-links against: ${AGENT_PROMPT_INTERFACE_LINK_LIBS}")
endif()

# ------------------------------------------------------------
# 3. Result
# ------------------------------------------------------------
list(LENGTH all_files all_files_count)
if(violations)
    foreach(violation IN LISTS violations)
        message(STATUS "AGENT PROMPT BOUNDARY VIOLATION: ${violation}")
    endforeach()
    message(FATAL_ERROR "P1-IS007 Rev1.1 Agent-Prompt boundary check failed")
endif()

message(STATUS "P1-IS007 Rev1.1 Agent-Prompt boundary check passed "
               "(${all_files_count} files, no forbidden dependencies)")