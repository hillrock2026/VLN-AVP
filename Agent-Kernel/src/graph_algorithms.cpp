#include <agent_kernel/workflow/graph_algorithms.hpp>
#include <agent_kernel/workflow/workflow_graph.hpp>
#include <algorithm>
#include <queue>
#include <unordered_map>
#include <unordered_set>

namespace ak {

bool ValidateGraph(const WorkflowGraph& graph) {
    return graph.Validate();
}

std::optional<TopologicalOrder> ComputeTopologicalOrder(const WorkflowGraph& graph) {
    // Kahn's algorithm
    auto allNodes = graph.FindRootNodes();
    // Collect all node IDs
    std::vector<TaskID> allIds;
    // Use BFS to collect all nodes
    std::queue<TaskID> bfs;
    std::unordered_set<TaskID, std::hash<KernelObjectID>> visited;
    for (const auto& root : graph.FindRootNodes()) {
        bfs.push(root);
        visited.insert(root);
    }
    while (!bfs.empty()) {
        auto current = bfs.front(); bfs.pop();
        allIds.push_back(current);
        for (const auto& succ : graph.GetSuccessors(current)) {
            if (visited.find(succ) == visited.end()) {
                visited.insert(succ);
                bfs.push(succ);
            }
        }
    }

    // Compute in-degree
    std::unordered_map<TaskID, int, std::hash<KernelObjectID>> inDegree;
    for (const auto& id : allIds) {
        inDegree[id] = 0;
    }
    for (const auto& id : allIds) {
        for (const auto& succ : graph.GetSuccessors(id)) {
            inDegree[succ]++;
        }
    }

    std::queue<TaskID> queue;
    for (const auto& id : allIds) {
        if (inDegree[id] == 0) queue.push(id);
    }

    TopologicalOrder result;
    while (!queue.empty()) {
        auto current = queue.front(); queue.pop();
        result.orderedTasks.push_back(current);
        for (const auto& succ : graph.GetSuccessors(current)) {
            if (--inDegree[succ] == 0) queue.push(succ);
        }
    }

    if (result.orderedTasks.size() == visited.size()) {
        return result;
    }
    return std::nullopt;
}

CycleInfo DetectCycle(const WorkflowGraph& graph) {
    CycleInfo info;
    info.hasCycle = false;
    // Simplified: try topological sort - if it fails, there's a cycle
    auto order = ComputeTopologicalOrder(graph);
    info.hasCycle = !order.has_value();
    return info;
}

std::vector<TaskID> GetPredecessors(const WorkflowGraph& graph, TaskID nodeId) {
    return graph.GetPredecessors(nodeId);
}

std::vector<TaskID> GetSuccessors(const WorkflowGraph& graph, TaskID nodeId) {
    return graph.GetSuccessors(nodeId);
}

std::vector<TaskID> FindRootNodes(const WorkflowGraph& graph) {
    return graph.FindRootNodes();
}

std::vector<TaskID> FindLeafNodes(const WorkflowGraph& graph) {
    return graph.FindLeafNodes();
}

std::size_t CountNodes(const WorkflowGraph& graph) {
    return graph.GetNodeCount();
}

std::size_t CountEdges(const WorkflowGraph& graph) {
    return graph.GetEdgeCount();
}

}  // namespace ak
