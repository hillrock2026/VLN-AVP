# ============================================================
# check_prompt_boundaries.cmake - P1-IS007 Rev1.1 static
# boundary check (Prompt boundary)
# ============================================================
# Verifies, without requiring a behavioral test:
#
#  1. Every Prompt public header and implementation source is
#     scanned.
#  2. No Runtime internal/public header, no Scheduler,
#     Executor, Capability Resolver, Event Bus, Workflow, Task,
#     or Session usage exists in the Prompt boundary (PRM-008).
#  3. No Agent/Context/Planner/Memory/Tool internal include
#     exists (PRM-024..PRM-027).
#  4. No concrete Model-provider SDK include exists (PRM-029).
#  5. No ROS2 include exists (TOL-027).
#  6. The prohibited public API names do not appear on the
#     Prompt surface: no active-retrieval operations, no
#     lifecycle operations, and no Tool/Memory/Context/Planner
#     ownership operations (PRM-036, PRM-048, Chapter 7.8).
#  7. No mirror domain models (PromptMemory, PromptContext,
#     PromptPlanner, PromptTool) appear in the Prompt boundary
#     (PRM-038, AC-029).
#  8. The agent_kernel_prompt target links only
#     agent_kernel_foundation (PRM-030).
#
# Usage (registered as a CTest):
#   cmake -DPROMPT_INCLUDE_DIR=<dir>
#         -DPROMPT_SOURCE_DIR=<dir>
#         -DPROMPT_LINK_LIBS=<target LINK_LIBRARIES>
#         -DPROMPT_INTERFACE_LINK_LIBS=<target INTERFACE_LINK_LIBRARIES>
#         -P check_prompt_boundaries.cmake
# ============================================================

if(NOT DEFINED PROMPT_INCLUDE_DIR OR NOT DEFINED PROMPT_SOURCE_DIR)
    message(FATAL_ERROR "PROMPT_INCLUDE_DIR and PROMPT_SOURCE_DIR are required")
endif()

set(violations "")

# ------------------------------------------------------------
# 1. Include-boundary scan (all headers and sources)
# ------------------------------------------------------------
file(GLOB_RECURSE prompt_headers
    "${PROMPT_INCLUDE_DIR}/*.hpp")
file(GLOB prompt_sources
    "${PROMPT_SOURCE_DIR}/*.cpp")

if(NOT prompt_headers)
    message(FATAL_ERROR "No Prompt headers found under ${PROMPT_INCLUDE_DIR}")
endif()
if(NOT prompt_sources)
    message(FATAL_ERROR "No Prompt sources found under ${PROMPT_SOURCE_DIR}")
endif()

set(all_files ${prompt_headers} ${prompt_sources})

foreach(file IN LISTS all_files)
    file(READ "${file}" content)
    string(REGEX MATCHALL "#include[ \t]*[<\"][^>\"]+[>\"]" include_tokens "${content}")
    foreach(token IN LISTS include_tokens)
        string(REGEX REPLACE "^#include[ \t]*[<\"]" "" name "${token}")
        string(REGEX REPLACE "[>\"]$" "" name "${name}")

        # Quoted includes are not used by the Prompt surface.
        if(token MATCHES "^#include[ \t]*\"")
            list(APPEND violations
                "${file}: quoted include \"${name}\" is not part of the Prompt boundary")
            continue()
        endif()

        # Allowed: standard library headers, the Prompt
        # boundary, and the Kernel Foundation.
        if(name MATCHES "^agent_kernel/prompt/")
            continue()
        endif()
        if(name MATCHES "^agent_kernel/foundation/")
            continue()
        endif()

        if(name MATCHES "^agent_kernel/")
            list(APPEND violations
                "${file}: forbidden subsystem/include <${name}> (Agent/Context/Planner/Memory/Tool/Agent-Prompt boundary violation)")
            continue()
        endif()

        if(name MATCHES "^ak/")
            list(APPEND violations
                "${file}: forbidden include <${name}> (non-Prompt Agent Kernel header)")
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

foreach(file IN LISTS prompt_headers)
    file(READ "${file}" content)
    # Strip comments first: conformance documentation may name
    # prohibited identifiers, so the scan verifies the actual
    # public surface rather than documentation text.
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
# 1c. No mirror domain models (PRM-038, AC-029)
# ------------------------------------------------------------
set(mirror_model_names
    "PromptMemory"
    "PromptContext"
    "PromptPlanner"
    "PromptTool")
foreach(file IN LISTS all_files)
    file(READ "${file}" content)
    string(REGEX REPLACE [==[/\*[^*]*\*+([^/*][^*]*\*+)*/]==] "" content "${content}")
    string(REGEX REPLACE [==[//.*]==] "" content "${content}")
    foreach(name IN LISTS mirror_model_names)
        if(content MATCHES "${name}")
            list(APPEND violations
                "${file}: prohibited mirror domain model identifier '${name}' (PRM-038)")
        endif()
    endforeach()
endforeach()

# ------------------------------------------------------------
# 2. Link-boundary check (PRM-030)
# ------------------------------------------------------------
if(NOT DEFINED PROMPT_LINK_LIBS OR NOT PROMPT_LINK_LIBS STREQUAL "agent_kernel_foundation")
    list(APPEND violations
        "agent_kernel_prompt links against: ${PROMPT_LINK_LIBS}")
endif()

if(DEFINED PROMPT_INTERFACE_LINK_LIBS AND NOT PROMPT_INTERFACE_LINK_LIBS STREQUAL ""
   AND NOT PROMPT_INTERFACE_LINK_LIBS STREQUAL "agent_kernel_foundation")
    list(APPEND violations
        "agent_kernel_prompt interface-links against: ${PROMPT_INTERFACE_LINK_LIBS}")
endif()

# ------------------------------------------------------------
# 3. Result
# ------------------------------------------------------------
list(LENGTH all_files all_files_count)
if(violations)
    foreach(violation IN LISTS violations)
        message(STATUS "PROMPT BOUNDARY VIOLATION: ${violation}")
    endforeach()
    message(FATAL_ERROR "P1-IS007 Rev1.1 Prompt boundary check failed")
endif()

message(STATUS "P1-IS007 Rev1.1 Prompt boundary check passed "
               "(${all_files_count} files, no forbidden dependencies)")