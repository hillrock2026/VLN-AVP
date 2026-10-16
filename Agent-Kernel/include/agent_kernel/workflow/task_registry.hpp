// ============================================================
// Agent Kernel — TaskRegistry
// ============================================================
// Internal registry of Task instances owned by a Workflow.
//
// TaskRegistry is an implementation component of Workflow.
// It is NOT a Kernel Domain Object. It does NOT inherit from
// KernelObject. It does NOT have identity, state, lifecycle,
// or observers.
//
// Responsibilities:
// - Register newly created Tasks
// - Unregister destroyed Tasks
// - Find a Task by ID
// - Check if a Task exists
// - Enumerate all registered Tasks
// - Report count
//
// NON-responsibilities:
// - Does NOT execute Tasks
// - Does NOT resolve dependencies
// - Does NOT run graph algorithms
// - Does NOT cache or persist
// ============================================================

#pragma once

#include <memory>
#include <vector>

#include <agent_kernel/object_id.hpp>

namespace ak {

// Forward declaration
class Task;

// ============================================================
// TaskRegistry
// ============================================================
class TaskRegistry {
public:
    TaskRegistry() noexcept = default;
    ~TaskRegistry() noexcept = default;

    TaskRegistry(const TaskRegistry&) = delete;
    TaskRegistry& operator=(const TaskRegistry&) = delete;
    TaskRegistry(TaskRegistry&&) noexcept;
    TaskRegistry& operator=(TaskRegistry&&) noexcept;

    // -- Registration --
    void Register(TaskID id, std::unique_ptr<Task> task);
    std::unique_ptr<Task> Unregister(TaskID id);

    // -- Lookup --
    [[nodiscard]] Task* Find(TaskID id) const noexcept;

    // -- Query --
    [[nodiscard]] bool Contains(TaskID id) const noexcept;
    [[nodiscard]] std::size_t Count() const noexcept;

    // -- Enumeration --
    [[nodiscard]] std::vector<TaskID> Enumerate() const;

    // -- Clear --
    void Clear() noexcept;

private:
    std::vector<std::pair<TaskID, std::unique_ptr<Task>>> tasks_;
};

}  // namespace ak
