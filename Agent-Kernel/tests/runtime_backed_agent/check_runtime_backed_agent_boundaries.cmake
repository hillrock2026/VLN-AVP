# ============================================================
# check_runtime_backed_agent_boundaries.cmake - TASK 3.3
# static boundary verification (Contract 7/8; plan section 18)
# ============================================================
# Verifies:
#   1. The Agent-owned runtime-backed execution composition
#      (agent_kernel_runtime_backed_agent) links the sanctioned
#      integration bridge (agent_kernel_runtime_integration) and
#      does NOT link agent_kernel_runtime directly.
#   2. The composition headers and sources contain no Runtime
#      include: no <runtime.h>, no Runtime internals, no
#      Scheduler / Executor / CapabilityResolver / EventBus
#      types, no quoted includes.
# ============================================================

set(violations "")

# ------------------------------------------------------------
# 1. Link boundary
# ------------------------------------------------------------
if(DEFINED RB_LINK_LIBS)
    set(value "${RB_LINK_LIBS}")
    if(value MATCHES "(^|;)agent_kernel_runtime($|;)")
        list(APPEND violations
            "agent_kernel_runtime_backed_agent links a Runtime target directly: ${value}")
    endif()
    if(NOT value MATCHES "agent_kernel_runtime_integration")
        list(APPEND violations
            "agent_kernel_runtime_backed_agent does not link the sanctioned integration bridge: ${value}")
    endif()
endif()

if(DEFINED RB_INTERFACE_LINK_LIBS)
    set(value "${RB_INTERFACE_LINK_LIBS}")
    if(value MATCHES "(^|;)agent_kernel_runtime($|;)")
        list(APPEND violations
            "agent_kernel_runtime_backed_agent exposes a Runtime target through its interface: ${value}")
    endif()
endif()

# ------------------------------------------------------------
# 2. Include-boundary scan
# ------------------------------------------------------------
if(NOT DEFINED RB_INCLUDE_DIR OR NOT DEFINED RB_SOURCE_DIR)
    message(FATAL_ERROR "RB boundary-check directories are required")
endif()

file(GLOB_RECURSE composition_headers "${RB_INCLUDE_DIR}/*.hpp")
file(GLOB_RECURSE composition_sources "${RB_SOURCE_DIR}/*.cpp")

if(NOT composition_headers)
    message(FATAL_ERROR "No composition headers found under ${RB_INCLUDE_DIR}")
endif()

set(scan_files ${composition_headers} ${composition_sources})

foreach(file IN LISTS scan_files)
    file(READ "${file}" content)
    string(REGEX MATCHALL "#include[ \t]*[<\"][^>\"]+[>\"]" include_tokens "${content}")
    foreach(token IN LISTS include_tokens)
        string(REGEX REPLACE "^#include[ \t]*[<\"]" "" name "${token}")
        string(REGEX REPLACE "[>\"]$" "" name "${name}")

        # Any Runtime / Scheduler / Executor / CapabilityResolver /
        # EventBus / Runtime-internal include is forbidden in the
        # Agent-owned composition. Quoted includes are forbidden
        # (no local include bypass).
        if(name MATCHES "^agent_kernel/runtime/" OR name MATCHES "^runtime"
           OR name MATCHES "^agent_kernel/executor" OR name MATCHES "^agent_kernel/scheduler"
           OR name MATCHES "^agent_kernel/capability" OR name MATCHES "^agent_kernel/workflow"
           OR name MATCHES "^agent_kernel/task" OR name MATCHES "^capability_"
           OR name MATCHES "^event_bus" OR name MATCHES "^runtime_")
            list(APPEND violations
                "${file}: forbidden Runtime include <${name}>")
        endif()

        if(name MATCHES "^\".*\"$")
            list(APPEND violations
                "${file}: forbidden quoted include \"${name}\"")
        endif()
    endforeach()
endforeach()

# ------------------------------------------------------------
# 3. Result
# ------------------------------------------------------------
if(violations)
    foreach(violation IN LISTS violations)
        message(STATUS "RUNTIME-BACKED-AGENT BOUNDARY VIOLATION: ${violation}")
    endforeach()
    message(FATAL_ERROR "Runtime-backed agent boundary check failed")
endif()

message(STATUS "Runtime-backed agent boundary check passed")