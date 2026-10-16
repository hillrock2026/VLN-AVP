#include <agent_kernel/workflow/graph_edge.hpp>

namespace ak {

GraphEdge::GraphEdge(TaskID from, TaskID to, DependencyType type) noexcept
    : from_(from), to_(to), type_(type) {}

TaskID GraphEdge::GetFrom() const noexcept { return from_; }
TaskID GraphEdge::GetTo() const noexcept { return to_; }
DependencyType GraphEdge::GetType() const noexcept { return type_; }

}  // namespace ak
