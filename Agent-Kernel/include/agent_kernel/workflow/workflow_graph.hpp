// ============================================================
// Agent Kernel — WorkflowGraph
// ============================================================
// WorkflowGraph represents the immutable topology of a
// Workflow's Tasks.
//
// Responsibilities:
// - Owns all GraphNode instances (topology vertices)
// - Owns all GraphEdge instances (dependency relationships)
// - Validates graph structure (no cycles, all refs valid)
// - Provides traversal interfaces (predecessors, successors)
// - Provides topology queries (root/leaf nodes, order)
//
// NON-responsibilities:
// - Does NOT own or reference Task objects
// - Does NOT contain execution state
// - Does NOT execute anything
// - Does NOT know about Scheduler or Executor
//
// WorkflowGraph is owned by Workflow (composition).
// ============================================================

#pragma once

#include <memory>
#include <vector>
#include <unordered_map>
#include <optional>

#include <agent_kernel/object_id.hpp>
#include <agent_kernel/state.hpp>
#include <agent_kernel/workflow/graph_node.hpp>
#include <agent_kernel/workflow/graph_edge.hpp>
#include <agent_kernel/workflow/graph_algorithms.hpp>

namespace ak {

// ============================================================
// WorkflowGraph
// ============================================================
class WorkflowGraph {
public:
    WorkflowGraph() noexcept = default;
    ~WorkflowGraph() noexcept = default;

    WorkflowGraph(const WorkflowGraph&) = delete;
    WorkflowGraph& operator=(const WorkflowGraph&) = delete;
    WorkflowGraph(WorkflowGraph&&) noexcept;
    WorkflowGraph& operator=(WorkflowGraph&&) noexcept;

    // -- Node management --
    void AddNode(TaskID id);
    void RemoveNode(TaskID id);
    [[nodiscard]] bool HasNode(TaskID id) const noexcept;

    // -- Edge management --
    void AddEdge(TaskID from, TaskID to,
                 DependencyType type = DependencyType::kDataDependency);
    void RemoveEdge(TaskID from, TaskID to);
    [[nodiscard]] bool HasEdge(TaskID from, TaskID to) const noexcept;

    // -- Topology queries (delegate to graph_algorithms) --
    [[nodiscard]] bool Validate() const;
    [[nodiscard]] std::optional<TopologicalOrder> ComputeOrder() const;
    [[nodiscard]] CycleInfo FindCycle() const;

    [[nodiscard]] std::vector<TaskID> GetPredecessors(TaskID nodeId) const;
    [[nodiscard]] std::vector<TaskID> GetSuccessors(TaskID nodeId) const;
    [[nodiscard]] std::vector<TaskID> FindRootNodes() const;
    [[nodiscard]] std::vector<TaskID> FindLeafNodes() const;

    // -- Counts --
    [[nodiscard]] std::size_t GetNodeCount() const noexcept;
    [[nodiscard]] std::size_t GetEdgeCount() const noexcept;

    // -- Clear --
    void Clear() noexcept;

private:
    std::unordered_map<TaskID, GraphNode> nodes_;
    std::vector<GraphEdge> edges_;
};

}  // namespace ak
