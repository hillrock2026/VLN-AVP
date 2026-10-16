add_library(agent_kernel STATIC
    state.cpp
    object_id.cpp
    graph_node.cpp
    graph_edge.cpp
    graph_algorithms.cpp
    workflow_graph.cpp
    task_registry.cpp
    workflow_registry.cpp
    task.cpp
    workflow.cpp
    session.cpp
    session_builder.cpp
)

target_include_directories(agent_kernel
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_compile_features(agent_kernel PUBLIC cxx_std_20)

# P1-IS001: the legacy kernel model consumes the neutral
# Kernel Foundation; the Foundation target itself links
# against nothing.
target_link_libraries(agent_kernel PUBLIC agent_kernel_foundation)

add_subdirectory(agent)
add_subdirectory(agent/composition)
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
