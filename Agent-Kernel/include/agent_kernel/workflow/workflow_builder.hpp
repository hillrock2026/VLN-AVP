// ============================================================
// Agent Kernel — WorkflowBuilder
// ============================================================
// Lightweight builder for constructing Workflow instances.
//
// WorkflowBuilder abstracts Workflow construction complexity
// without exposing internal initialization details. It is
// NOT a runtime component — it only configures structural
// properties before the Workflow is created.
//
// WorkflowBuilder does NOT:
// - Initialize runtime subsystems
// - Create Scheduler or Executor
// - Register services
// - Start any execution
//
// Usage:
//   auto workflow = WorkflowBuilder()
//       .WithID(WorkflowID::Generate())
//       .WithParentSession(sessionId)
//       .WithName("DataPipeline")
//       .Build();
// ============================================================

#pragma once

#include <memory>
#include <string>
#include <cstdint>
#include <optional>

#include <agent_kernel/object_id.hpp>
#include <agent_kernel/foundation/kernel_metadata.hpp>
#include <agent_kernel/workflow/workflow_configuration.hpp>

namespace ak {

// Forward declaration
class Workflow;

// ============================================================
// WorkflowBuilder
// ============================================================
class WorkflowBuilder {
public:
    WorkflowBuilder() noexcept = default;

    // -- Identity --
    WorkflowBuilder& WithID(WorkflowID id) noexcept;
    WorkflowBuilder& WithParentSession(SessionID sessionId) noexcept;
    WorkflowBuilder& WithName(const std::string& name);

    // -- Capacity --
    WorkflowBuilder& WithMaxTasks(std::uint32_t maxTasks) noexcept;

    // -- Build --
    [[nodiscard]] std::unique_ptr<Workflow> Build();

private:
    std::optional<WorkflowID> id_;
    std::optional<SessionID> parentSession_;
    WorkflowConfiguration config_;
};

}  // namespace ak
