#include <agent_kernel/workflow/task_registry.hpp>
#include <agent_kernel/task.hpp>
#include <algorithm>

namespace ak {

TaskRegistry::TaskRegistry(TaskRegistry&&) noexcept = default;
TaskRegistry& TaskRegistry::operator=(TaskRegistry&&) noexcept = default;

void TaskRegistry::Register(TaskID id, std::unique_ptr<Task> task) {
    tasks_.emplace_back(id, std::move(task));
}

std::unique_ptr<Task> TaskRegistry::Unregister(TaskID id) {
    auto it = std::find_if(tasks_.begin(), tasks_.end(),
        [id](const auto& pair) { return pair.first == id; });
    if (it != tasks_.end()) {
        auto task = std::move(it->second);
        tasks_.erase(it);
        return task;
    }
    return nullptr;
}

Task* TaskRegistry::Find(TaskID id) const noexcept {
    auto it = std::find_if(tasks_.begin(), tasks_.end(),
        [id](const auto& pair) { return pair.first == id; });
    return (it != tasks_.end()) ? it->second.get() : nullptr;
}

bool TaskRegistry::Contains(TaskID id) const noexcept {
    return std::any_of(tasks_.begin(), tasks_.end(),
        [id](const auto& pair) { return pair.first == id; });
}

std::size_t TaskRegistry::Count() const noexcept {
    return tasks_.size();
}

std::vector<TaskID> TaskRegistry::Enumerate() const {
    std::vector<TaskID> ids;
    ids.reserve(tasks_.size());
    for (const auto& [id, _] : tasks_) {
        ids.push_back(id);
    }
    return ids;
}

void TaskRegistry::Clear() noexcept {
    tasks_.clear();
}

}  // namespace ak
