# ============================================================
# check_model_boundaries.cmake - P1-IS008 Rev1.0 static
# boundary check (Model boundary)
# ============================================================
# Verifies, without requiring a behavioral test:
#
#  1. Every Model public header and implementation source is
#     scanned.
#  2. Only standard headers, the Model boundary, and the Kernel
#     Foundation are included (P1-IS008 Rev1.0 Chapters 15, 16).
#  3. No Runtime/Scheduler/Executor/CapabilityResolver/EventBus/
#     Task/Workflow/Session include exists (Chapter 16, FD-004).
#  4. No Memory/Context/Planner/Tool/Agent/Prompt include exists
#     (FD-007..FD-010, Chapter 16).
#  5. No concrete Model-provider SDK or ROS2 include exists
#     (Chapters 11, 16; FD-011, FD-012).
#  6. The prohibited public API names do not appear on the
#     Model surface (no Tool execution, no Runtime access, no
#     Memory/Context/Planner/Prompt ownership, no registry/
#     router/scheduler/executor infrastructure).
#  7. The agent_kernel_model target links only
#     agent_kernel_foundation (Chapter 18).
#
# Usage (registered as a CTest):
#   cmake -DMODEL_INCLUDE_DIR=<dir>
#         -DMODEL_SOURCE_DIR=<dir>
#         -DMODEL_LINK_LIBS=<target LINK_LIBRARIES>
#         -DMODEL_INTERFACE_LINK_LIBS=<target INTERFACE_LINK_LIBRARIES>
#         -P check_model_boundaries.cmake
# ============================================================

if(NOT DEFINED MODEL_INCLUDE_DIR OR NOT DEFINED MODEL_SOURCE_DIR)
    message(FATAL_ERROR "MODEL_INCLUDE_DIR and MODEL_SOURCE_DIR are required")
endif()

set(violations "")

# ------------------------------------------------------------
# 1. Include-boundary scan (all headers and sources)
# ------------------------------------------------------------
file(GLOB_RECURSE model_headers
    "${MODEL_INCLUDE_DIR}/*.hpp")
file(GLOB model_sources
    "${MODEL_SOURCE_DIR}/*.cpp")

if(NOT model_headers)
    message(FATAL_ERROR "No Model headers found under ${MODEL_INCLUDE_DIR}")
endif()
if(NOT model_sources)
    message(FATAL_ERROR "No Model sources found under ${MODEL_SOURCE_DIR}")
endif()

set(all_files ${model_headers} ${model_sources})

foreach(file IN LISTS all_files)
    file(READ "${file}" content)
    string(REGEX MATCHALL "#include[ \t]*[<\"][^>\"]+[>\"]" include_tokens "${content}")
    foreach(token IN LISTS include_tokens)
        string(REGEX REPLACE "^#include[ \t]*[<\"]" "" name "${token}")
        string(REGEX REPLACE "[>\"]$" "" name "${name}")

        # Quoted includes are not used by the Model surface.
        if(token MATCHES "^#include[ \t]*\"")
            list(APPEND violations
                "${file}: quoted include \"${name}\" is not part of the Model boundary")
            continue()
        endif()

        # Allowed: standard library headers, the Model boundary,
        # and the Kernel Foundation.
        if(name MATCHES "^agent_kernel/model/")
            continue()
        endif()
        if(name MATCHES "^agent_kernel/foundation/")
            continue()
        endif()

        if(name MATCHES "^agent_kernel/")
            list(APPEND violations
                "${file}: forbidden subsystem/include <${name}> (Agent/Context/Planner/Memory/Tool/Prompt boundary violation, P1-IS008 Chapter 16)")
            continue()
        endif()

        if(name MATCHES "^ak/")
            list(APPEND violations
                "${file}: forbidden include <${name}> (non-Model Agent Kernel header)")
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
# 1b. Prohibited public API surface scan (Chapters 7, 9, 16)
# ------------------------------------------------------------
set(forbidden_api_names
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
    "ModelScheduler"
    "ModelExecutor"
    "ModelCache"
    "ModelSession"
    "ModelFactory"
    "ModelStream"
    "ProviderClient"
    "OpenAIClient")

foreach(file IN LISTS model_headers)
    file(READ "${file}" content)
    # Strip comments first: conformance documentation may name
    # prohibited identifiers, so the scan verifies the actual
    # public surface rather than documentation text.
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
# 2. Link-boundary check (Chapter 18)
# ------------------------------------------------------------
if(NOT DEFINED MODEL_LINK_LIBS OR NOT MODEL_LINK_LIBS STREQUAL "agent_kernel_foundation")
    list(APPEND violations
        "agent_kernel_model links against: ${MODEL_LINK_LIBS}")
endif()

if(DEFINED MODEL_INTERFACE_LINK_LIBS AND NOT MODEL_INTERFACE_LINK_LIBS STREQUAL ""
   AND NOT MODEL_INTERFACE_LINK_LIBS STREQUAL "agent_kernel_foundation")
    list(APPEND violations
        "agent_kernel_model interface-links against: ${MODEL_INTERFACE_LINK_LIBS}")
endif()

# ------------------------------------------------------------
# 3. Result
# ------------------------------------------------------------
list(LENGTH all_files all_files_count)
if(violations)
    foreach(violation IN LISTS violations)
        message(STATUS "MODEL BOUNDARY VIOLATION: ${violation}")
    endforeach()
    message(FATAL_ERROR "P1-IS008 Rev1.0 Model boundary check failed")
endif()

message(STATUS "P1-IS008 Rev1.0 Model boundary check passed "
               "(${all_files_count} files, no forbidden dependencies)")
