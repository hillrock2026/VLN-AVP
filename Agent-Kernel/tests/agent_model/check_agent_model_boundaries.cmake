# ============================================================
# check_agent_model_boundaries.cmake - P1-IS008 Rev1.0
# static boundary check (Agent-owned Model boundary)
# ============================================================
# Verifies, without requiring a behavioral test:
#
#  1. Every AgentModel public header and implementation source
#     is scanned.
#  2. Only standard headers, the AgentModel boundary, the
#     Model public contract, and the Kernel Foundation are
#     included (P1-IS008 Rev1.0 Chapters 15, 16).
#  3. No Runtime/Scheduler/Executor/CapabilityResolver/EventBus
#     include exists (Chapter 16, FD-004).
#  4. No Memory/Context/Planner/Tool/Agent/Prompt/FWA include
#     exists (FD-007..FD-010; ModelAction stays Agent-owned in
#     fwa/ and is not part of the Model coordination boundary).
#  5. No concrete Model-provider SDK or ROS2 include exists
#     (Chapter 16, FD-011/FD-012).
#  6. The prohibited public API names do not appear on the
#     AgentModel surface (no Tool execution, no Runtime access,
#     no ModelAction, no second coordination API).
#  7. AgentModelHost exposes no public Model() accessor.
#  8. The agent_kernel_agent_model target links only
#     agent_kernel_model + agent_kernel_foundation (Chapter 18).
#
# Usage (registered as a CTest):
#   cmake -DAGENT_MODEL_INCLUDE_DIR=<dir>
#         -DAGENT_MODEL_SOURCE_DIR=<dir>
#         -DAGENT_MODEL_LINK_LIBS=<target LINK_LIBRARIES>
#         -DAGENT_MODEL_INTERFACE_LINK_LIBS=<target INTERFACE_LINK_LIBRARIES>
#         -P check_agent_model_boundaries.cmake
# ============================================================

if(NOT DEFINED AGENT_MODEL_INCLUDE_DIR OR NOT DEFINED AGENT_MODEL_SOURCE_DIR)
    message(FATAL_ERROR "AGENT_MODEL_INCLUDE_DIR and AGENT_MODEL_SOURCE_DIR are required")
endif()

set(violations "")

# ------------------------------------------------------------
# 1. Include-boundary scan (all headers and sources)
# ------------------------------------------------------------
file(GLOB_RECURSE agent_model_headers
    "${AGENT_MODEL_INCLUDE_DIR}/*.hpp")
file(GLOB agent_model_sources
    "${AGENT_MODEL_SOURCE_DIR}/*.cpp")

if(NOT agent_model_headers)
    message(FATAL_ERROR "No AgentModel headers found under ${AGENT_MODEL_INCLUDE_DIR}")
endif()
if(NOT agent_model_sources)
    message(FATAL_ERROR "No AgentModel sources found under ${AGENT_MODEL_SOURCE_DIR}")
endif()

set(all_files ${agent_model_headers} ${agent_model_sources})

foreach(file IN LISTS all_files)
    file(READ "${file}" content)
    string(REGEX MATCHALL "#include[ \t]*[<\"][^>\"]+[>\"]" include_tokens "${content}")
    foreach(token IN LISTS include_tokens)
        string(REGEX REPLACE "^#include[ \t]*[<\"]" "" name "${token}")
        string(REGEX REPLACE "[>\"]$" "" name "${name}")

        # Quoted includes are not used by the AgentModel surface.
        if(token MATCHES "^#include[ \t]*\"")
            list(APPEND violations
                "${file}: quoted include \"${name}\" is not part of the AgentModel boundary")
            continue()
        endif()

        # Allowed: standard library headers, the AgentModel
        # boundary, the Model public contract, and the Kernel
        # Foundation.
        if(name MATCHES "^agent_kernel/agent_model/")
            continue()
        endif()
        if(name MATCHES "^agent_kernel/model/")
            continue()
        endif()
        if(name MATCHES "^agent_kernel/foundation/")
            continue()
        endif()

        if(name MATCHES "^agent_kernel/")
            list(APPEND violations
                "${file}: forbidden subsystem/include <${name}> (Agent/Context/Planner/Memory/Tool/Prompt/FWA boundary violation, P1-IS008 Chapter 16)")
            continue()
        endif()

        if(name MATCHES "^ak/")
            list(APPEND violations
                "${file}: forbidden include <${name}> (non-AgentModel Agent Kernel header)")
            continue()
        endif()

        if(name MATCHES "^runtime" OR name MATCHES "^capability_"
           OR name MATCHES "^event_bus" OR name MATCHES "^i_capability"
           OR name MATCHES "^scheduler" OR name MATCHES "^executor"
           OR name MATCHES "^session" OR name MATCHES "^workflow"
           OR name MATCHES "^task")
            list(APPEND violations
                "${file}: forbidden Runtime/subsystem include <${name}> (Runtime boundary violation, FD-004)")
            continue()
        endif()

        # Concrete Model-provider SDKs and ROS2 (Chapter 16).
        if(name MATCHES "openai" OR name MATCHES "deepseek"
           OR name MATCHES "qwen" OR name MATCHES "anthropic"
           OR name MATCHES "gemini" OR name MATCHES "transformers"
           OR name MATCHES "vllm" OR name MATCHES "llama"
           OR name MATCHES "rclcpp" OR name MATCHES "rcl/")
            list(APPEND violations
                "${file}: forbidden Model-provider/ROS2 include <${name}> (FD-011/FD-012)")
            continue()
        endif()

        if(name MATCHES "/")
            list(APPEND violations
                "${file}: unexpected non-standard include <${name}>")
        endif()
    endforeach()
endforeach()

# ------------------------------------------------------------
# 1b. Prohibited public API surface scan (Chapters 8, 9, 16)
# ------------------------------------------------------------
set(forbidden_api_names
    "ModelAction"
    "ExecuteTool"
    "PrepareInvocation"
    "RegisterTool"
    "DiscoverTool"
    "GetCapability"
    "ToolExecution"
    "AgentToolHost"
    "AgentToolBinding"
    "RuntimeInteractionPort"
    "ScheduleWork"
    "ExecuteWork"
    "SubmitRuntimeRequest"
    "ObserveRuntimeStatus"
    "BindRuntimePublicApi"
    "ResolveRuntimeCapability"
    "PublishRuntimeEvent"
    "EventBus"
    "RetrieveMemory"
    "QueryMemory"
    "RetrieveContext"
    "QueryContext"
    "InvokePlanner"
    "CreatePlanner"
    "AssemblePrompt"
    "PromptAssembly"
    "CreatePrompt"
    "ModelRegistry"
    "ModelManager"
    "ModelRouter"
    "ProviderClient"
    "OpenAIClient")

foreach(file IN LISTS agent_model_headers)
    file(READ "${file}" content)
    string(REGEX REPLACE [==[/\*[^*]*\*+([^/*][^*]*\*+)*/]==] "" content "${content}")
    string(REGEX REPLACE [==[//.*]==] "" content "${content}")
    foreach(name IN LISTS forbidden_api_names)
        if(content MATCHES "${name}")
            list(APPEND violations
                "${file}: prohibited public API name '${name}' (P1-IS008 Chapter 16)")
        endif()
    endforeach()
endforeach()

# ------------------------------------------------------------
# 1c. No public Model() accessor on AgentModelHost
#     (Chapter 15 host pattern)
# ------------------------------------------------------------
set(host_file "${AGENT_MODEL_INCLUDE_DIR}/agent_model_host.hpp")
if(EXISTS "${host_file}")
    file(READ "${host_file}" host_content)
    string(REGEX REPLACE [==[/\*[^*]*\*+([^/*][^*]*\*+)*/]==] "" host_content "${host_content}")
    string(REGEX REPLACE [==[//.*]==] "" host_content "${host_content}")
    if(host_content MATCHES "Model\\(")
        list(APPEND violations
            "${host_file}: prohibited public Model() accessor (Chapter 15 host pattern)")
    endif()
endif()

# ------------------------------------------------------------
# 2. Link-boundary check (Chapter 18)
# ------------------------------------------------------------
set(expected_links "agent_kernel_model;agent_kernel_foundation")
if(NOT DEFINED AGENT_MODEL_LINK_LIBS OR NOT AGENT_MODEL_LINK_LIBS STREQUAL "${expected_links}")
    list(APPEND violations
        "agent_kernel_agent_model links against: ${AGENT_MODEL_LINK_LIBS}")
endif()

if(DEFINED AGENT_MODEL_INTERFACE_LINK_LIBS AND NOT AGENT_MODEL_INTERFACE_LINK_LIBS STREQUAL ""
   AND NOT AGENT_MODEL_INTERFACE_LINK_LIBS STREQUAL "${expected_links}")
    list(APPEND violations
        "agent_kernel_agent_model interface-links against: ${AGENT_MODEL_INTERFACE_LINK_LIBS}")
endif()

# ------------------------------------------------------------
# 3. Result
# ------------------------------------------------------------
list(LENGTH all_files all_files_count)
if(violations)
    foreach(violation IN LISTS violations)
        message(STATUS "AGENT MODEL BOUNDARY VIOLATION: ${violation}")
    endforeach()
    message(FATAL_ERROR "P1-IS008 Rev1.0 Agent-Model boundary check failed")
endif()

message(STATUS "P1-IS008 Rev1.0 Agent-Model boundary check passed "
               "(${all_files_count} files, no forbidden dependencies)")
