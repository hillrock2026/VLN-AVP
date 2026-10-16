#include <agent_kernel/workflow/workflow_graph.hpp>
#include <algorithm>
#include <queue>
#include <unordered_set>
#include <stdexcept>
#include <functional>

namespace ak {

WorkflowGraph::WorkflowGraph(WorkflowGraph&&) noexcept = default;
WorkflowGraph& WorkflowGraph::operator=(WorkflowGraph&&) noexcept = default;

void WorkflowGraph::AddNode(TaskID id) {
    if (nodes_.find(id) == nodes_.end()) {
        nodes_.emplace(id, GraphNode(id));
    }
}

void WorkflowGraph::RemoveNode(TaskID id) {
    nodes_.erase(id);
    edges_.erase(std::remove_if(edges_.begin(), edges_.end(),
        [id](const GraphEdge& e) {
            return e.GetFrom() == id || e.GetTo() == id;
        }), edges_.end());
}

bool WorkflowGraph::HasNode(TaskID id) const noexcept {
    return nodes_.find(id) != nodes_.end();
}

void WorkflowGraph::AddEdge(TaskID from, TaskID to, DependencyType type) {
    if (!HasNode(from)) AddNode(from);
    if (!HasNode(to)) AddNode(to);
    edges_.emplace_back(from, to, type);
}

void WorkflowGraph::RemoveEdge(TaskID from, TaskID to) {
    edges_.erase(std::remove_if(edges_.begin(), edges_.end(),
        [from, to](const GraphEdge& e) {
            return e.GetFrom() == from && e.GetTo() == to;
        }), edges_.end());
}

bool WorkflowGraph::HasEdge(TaskID from, TaskID to) const noexcept {
    return std::any_of(edges_.begin(), edges_.end(),
        [from, to](const GraphEdge& e) {
            return e.GetFrom() == from && e.GetTo() == to;
        });
}

bool WorkflowGraph::Validate() const {
    for (const auto& e : edges_) {
        if (e.GetFrom() == e.GetTo()) return false;
        if (!HasNode(e.GetFrom()) || !HasNode(e.GetTo())) return false;
    }
    return !FindCycle().hasCycle;
}

std::optional<TopologicalOrder> WorkflowGraph::ComputeOrder() const {
    if (nodes_.empty()) return TopologicalOrder{};

    // Kahn's algorithm using edges_ directly
    std::unordered_map<TaskID, int, std::hash<KernelObjectID>> inDegree;
    for (const auto& [id, _] : nodes_) {
        inDegree[id] = 0;
    }
    for (const auto& e : edges_) {
        inDegree[e.GetTo()]++;
    }

    std::queue<TaskID> queue;
    for (const auto& [id, _] : nodes_) {
        if (inDegree[id] == 0) queue.push(id);
    }

    TopologicalOrder result;
    while (!queue.empty()) {
        auto current = queue.front(); queue.pop();
        result.orderedTasks.push_back(current);
        for (const auto& e : edges_) {
            if (e.GetFrom() == current) {
                if (--inDegree[e.GetTo()] == 0) queue.push(e.GetTo());
            }
        }
    }

    if (result.orderedTasks.size() == nodes_.size()) {
        return result;
    }
    return std::nullopt;
}

CycleInfo WorkflowGraph::FindCycle() const {
    CycleInfo info;
    info.hasCycle = false;

    std::unordered_set<TaskID, std::hash<KernelObjectID>> white, grey, black;
    for (const auto& [id, _] : nodes_) white.insert(id);

    std::function<bool(TaskID)> dfs = [&](TaskID node) -> bool {
        white.erase(node);
        grey.insert(node);
        for (const auto& e : edges_) {
            if (e.GetFrom() == node) {
                TaskID succ = e.GetTo();
                if (black.count(succ)) continue;
                if (grey.count(succ)) {
                    info.hasCycle = true;
                    info.cyclePath.push_back(succ);
                    return true;
                }
                if (dfs(succ)) return true;
            }
        }
        grey.erase(node);
        black.insert(node);
        return false;
    };

    while (!white.empty() && !info.hasCycle) {
        dfs(*white.begin());
    }

    return info;
}

std::vector<TaskID> WorkflowGraph::GetPredecessors(TaskID nodeId) const {
    std::vector<TaskID> preds;
    for (const auto& e : edges_) {
        if (e.GetTo() == nodeId) {
            preds.push_back(e.GetFrom());
        }
    }
    return preds;
}

std::vector<TaskID> WorkflowGraph::GetSuccessors(TaskID nodeId) const {
    std::vector<TaskID> succs;
    for (const auto& e : edges_) {
        if (e.GetFrom() == nodeId) {
            succs.push_back(e.GetTo());
        }
    }
    return succs;
}

std::vector<TaskID> WorkflowGraph::FindRootNodes() const {
    std::vector<TaskID> roots;
    for (const auto& [id, _] : nodes_) {
        bool hasPredecessor = false;
        for (const auto& e : edges_) {
            if (e.GetTo() == id) { hasPredecessor = true; break; }
        }
        if (!hasPredecessor) roots.push_back(id);
    }
    return roots;
}

std::vector<TaskID> WorkflowGraph::FindLeafNodes() const {
    std::vector<TaskID> leaves;
    for (const auto& [id, _] : nodes_) {
        bool hasSuccessor = false;
        for (const auto& e : edges_) {
            if (e.GetFrom() == id) { hasSuccessor = true; break; }
        }
        if (!hasSuccessor) leaves.push_back(id);
    }
    return leaves;
}

std::size_t WorkflowGraph::GetNodeCount() const noexcept {
    return nodes_.size();
}

std::size_t WorkflowGraph::GetEdgeCount() const noexcept {
    return edges_.size();
}

void WorkflowGraph::Clear() noexcept {
    nodes_.clear();
    edges_.clear();
}

}  // namespace ak
