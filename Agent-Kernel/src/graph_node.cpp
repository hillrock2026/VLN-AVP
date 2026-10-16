#include <agent_kernel/workflow/graph_node.hpp>

namespace ak {

GraphNode::GraphNode(TaskID id) noexcept : taskId_(id) {}

TaskID GraphNode::GetTaskID() const noexcept {
    return taskId_;
}

const NodeAttributes& GraphNode::GetAttributes() const noexcept {
    return attributes_;
}

void GraphNode::SetAttributes(const NodeAttributes& attrs) noexcept {
    attributes_ = attrs;
}

}  // namespace ak
