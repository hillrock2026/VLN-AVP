#include <agent_kernel/session/workflow_registry.hpp>
#include <agent_kernel/workflow.hpp>
#include <algorithm>

namespace ak {

WorkflowRegistry::WorkflowRegistry(WorkflowRegistry&&) noexcept = default;
WorkflowRegistry& WorkflowRegistry::operator=(WorkflowRegistry&&) noexcept = default;

void WorkflowRegistry::Register(WorkflowID id, std::unique_ptr<Workflow> workflow) {
    workflows_.emplace_back(id, std::move(workflow));
}

std::unique_ptr<Workflow> WorkflowRegistry::Unregister(WorkflowID id) {
    auto it = std::find_if(workflows_.begin(), workflows_.end(),
        [id](const auto& pair) { return pair.first == id; });
    if (it != workflows_.end()) {
        auto wf = std::move(it->second);
        workflows_.erase(it);
        return wf;
    }
    return nullptr;
}

Workflow* WorkflowRegistry::Find(WorkflowID id) const noexcept {
    auto it = std::find_if(workflows_.begin(), workflows_.end(),
        [id](const auto& pair) { return pair.first == id; });
    return (it != workflows_.end()) ? it->second.get() : nullptr;
}

bool WorkflowRegistry::Contains(WorkflowID id) const noexcept {
    return std::any_of(workflows_.begin(), workflows_.end(),
        [id](const auto& pair) { return pair.first == id; });
}

std::size_t WorkflowRegistry::Count() const noexcept {
    return workflows_.size();
}

std::vector<WorkflowID> WorkflowRegistry::Enumerate() const {
    std::vector<WorkflowID> ids;
    ids.reserve(workflows_.size());
    for (const auto& [id, _] : workflows_) {
        ids.push_back(id);
    }
    return ids;
}

void WorkflowRegistry::Clear() noexcept {
    workflows_.clear();
}

}  // namespace ak
