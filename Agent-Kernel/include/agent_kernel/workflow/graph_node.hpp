// ============================================================
// Agent Kernel — GraphNode
// ============================================================
// A GraphNode represents one vertex in the Workflow topology.
//
// It contains only the node's identity (TaskID) and structural
// attributes. It does NOT contain:
//   - A pointer or reference to a Task object
//   - Execution state
//   - Runtime metadata
//   - Any behavior
//
// The Task object owns execution state. The GraphNode is only
// a topology placeholder.
//
// GraphNode is a value type. It is owned by WorkflowGraph.
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include <agent_kernel/object_id.hpp>

namespace ak {

// ============================================================
// NodeAttributes — structural metadata for a graph node
// ============================================================
// Future extension point: add node-level configuration that
// affects topology (e.g., node type tag, required capabilities)
// without touching the Task object.
struct NodeAttributes {
    // Reserved for future: type classification tag
    // std::string typeTag;

    // Reserved for future: expected duration hint (for scheduling)
    // std::chrono::milliseconds expectedDuration;
};

// ============================================================
// GraphNode — topology vertex
// ============================================================
class GraphNode {
public:
    explicit GraphNode(TaskID id) noexcept;

    // -- Identity --
    [[nodiscard]] TaskID GetTaskID() const noexcept;

    // -- Attributes (future extension) --
    [[nodiscard]] const NodeAttributes& GetAttributes() const noexcept;
    void SetAttributes(const NodeAttributes& attrs) noexcept;

    // -- Comparison --
    auto operator<=>(const GraphNode&) const = default;

private:
    TaskID taskId_;
    NodeAttributes attributes_;
};

}  // namespace ak
