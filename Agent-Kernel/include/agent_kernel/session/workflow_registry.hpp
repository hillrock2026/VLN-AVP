// ============================================================
// Agent Kernel — WorkflowRegistry
// ============================================================
// Internal registry of Workflow instances owned by a Session.
//
// WorkflowRegistry is an implementation component of Session.
// It is NOT a Kernel Domain Object. It does NOT inherit from
// KernelObject. It does NOT have identity, state, lifecycle,
// or observers.
//
// Responsibilities:
// - Register newly created Workflows
// - Unregister destroyed Workflows
// - Find a Workflow by ID
// - Check if a Workflow exists
// - Enumerate all registered Workflows
// - Report count
//
// NON-responsibilities:
// - Does NOT execute Workflows
// - Does NOT schedule anything
// - Does NOT cache or persist
// - Does NOT implement policies
// ============================================================

#pragma once

#include <memory>
#include <vector>
#include <optional>

#include <agent_kernel/object_id.hpp>

namespace ak {

// Forward declaration
class Workflow;

// ============================================================
// WorkflowRegistry
// ============================================================
class WorkflowRegistry {
public:
    WorkflowRegistry() noexcept = default;
    ~WorkflowRegistry() noexcept = default;

    WorkflowRegistry(const WorkflowRegistry&) = delete;
    WorkflowRegistry& operator=(const WorkflowRegistry&) = delete;
    WorkflowRegistry(WorkflowRegistry&&) noexcept;
    WorkflowRegistry& operator=(WorkflowRegistry&&) noexcept;

    // -- Registration --
    void Register(WorkflowID id,
                  std::unique_ptr<Workflow> workflow);
    std::unique_ptr<Workflow> Unregister(WorkflowID id);

    // -- Lookup --
    [[nodiscard]] Workflow* Find(WorkflowID id) const noexcept;

    // -- Query --
    [[nodiscard]] bool Contains(WorkflowID id) const noexcept;
    [[nodiscard]] std::size_t Count() const noexcept;

    // -- Enumeration --
    [[nodiscard]] std::vector<WorkflowID> Enumerate() const;

    // -- Clear --
    void Clear() noexcept;

private:
    std::vector<std::pair<WorkflowID, std::unique_ptr<Workflow>>> workflows_;
};

}  // namespace ak
