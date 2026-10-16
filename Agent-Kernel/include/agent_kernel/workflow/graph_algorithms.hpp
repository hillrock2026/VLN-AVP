// ============================================================
// Agent Kernel — GraphAlgorithms
// ============================================================
// Interface-only declarations for topology algorithms.
//
// These functions operate on the immutable topology model
// (WorkflowGraph) and return structural results. They do NOT
// modify the graph. They do NOT execute Tasks.
//
// The actual algorithm implementations belong to the runtime
// module (AK0030+). Only the interface contracts are defined
// here so that consumers (Scheduler, Validator) can write
// against stable signatures.
// ============================================================

#pragma once

#include <vector>
#include <optional>

#include <agent_kernel/object_id.hpp>

namespace ak {

// Forward declaration
class WorkflowGraph;

// ============================================================
// Topology query results
// ============================================================
struct TopologicalOrder {
    std::vector<TaskID> orderedTasks;

    [[nodiscard]] bool IsEmpty() const noexcept {
        return orderedTasks.empty();
    }
};

struct CycleInfo {
    bool hasCycle;
    std::vector<TaskID> cyclePath;  // empty if no cycle

    [[nodiscard]] explicit operator bool() const noexcept {
        return hasCycle;
    }
};

// ============================================================
// Algorithm interface declarations
// ============================================================

// Validates the graph structure. Returns true if the graph
// contains no cycles and all referenced nodes exist.
[[nodiscard]] bool ValidateGraph(const WorkflowGraph& graph);

// Computes a topological ordering of all nodes.
// Returns nullopt if the graph contains a cycle.
[[nodiscard]] std::optional<TopologicalOrder> ComputeTopologicalOrder(
    const WorkflowGraph& graph);

// Detects cycles in the graph. If a cycle exists, cyclePath
// contains one representative cycle.
[[nodiscard]] CycleInfo DetectCycle(const WorkflowGraph& graph);

// Returns all immediate predecessors of a node
// (nodes that must complete before nodeId).
[[nodiscard]] std::vector<TaskID> GetPredecessors(
    const WorkflowGraph& graph, TaskID nodeId);

// Returns all immediate successors of a node
// (nodes that depend on nodeId completing).
[[nodiscard]] std::vector<TaskID> GetSuccessors(
    const WorkflowGraph& graph, TaskID nodeId);

// Returns all nodes that have no incoming edges
// (entry points for scheduling).
[[nodiscard]] std::vector<TaskID> FindRootNodes(
    const WorkflowGraph& graph);

// Returns all nodes that have no outgoing edges
// (terminal points).
[[nodiscard]] std::vector<TaskID> FindLeafNodes(
    const WorkflowGraph& graph);

// Returns the number of nodes in the graph.
[[nodiscard]] std::size_t CountNodes(const WorkflowGraph& graph);

// Returns the number of edges in the graph.
[[nodiscard]] std::size_t CountEdges(const WorkflowGraph& graph);

}  // namespace ak
