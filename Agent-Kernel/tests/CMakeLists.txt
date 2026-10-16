# ============================================================
# tests/CMakeLists.txt - Test infrastructure
# ============================================================
# Phase 1 adds the Kernel Foundation conformance suite.
# Future phases will add:
#   add_subdirectory(unit)
#   add_subdirectory(integration)
#   add_subdirectory(benchmark)
#   add_subdirectory(regression)

message(STATUS "Test infrastructure ready - foundation tests enabled.")

add_subdirectory(agent)
add_subdirectory(memory)
add_subdirectory(context)
add_subdirectory(planner)
add_subdirectory(agent_planner)
add_subdirectory(tool)
add_subdirectory(agent_tool)
add_subdirectory(prompt)
add_subdirectory(agent_prompt)
add_subdirectory(model)
add_subdirectory(agent_model)
add_subdirectory(foundation)
add_subdirectory(first_working_agent)
add_subdirectory(runtime_integration)
add_subdirectory(runtime_backed_agent)
add_subdirectory(model_to_runtime)
add_subdirectory(agent_continuation)
