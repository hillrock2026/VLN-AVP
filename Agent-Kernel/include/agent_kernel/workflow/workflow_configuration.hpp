// ============================================================
// Agent Kernel — WorkflowConfiguration
// ============================================================
// Immutable value object containing Workflow construction
// parameters.
//
// WorkflowConfiguration is a value type set once during
// construction and read-only for the lifetime of the Workflow.
//
// It contains ONLY structural configuration:
// - Workflow name and version
// - Capacity limits (max tasks)
// - Custom properties (future extension)
//
// It does NOT contain runtime configuration:
// - Scheduling policy (belongs to Scheduler)
// - Retry policy (belongs to Executor)
// - Timeout policy (belongs to Executor or per-Task)
// - Concurrency limits (belongs to Executor)
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <optional>

namespace ak {

// ============================================================
// WorkflowConfiguration
// ============================================================
struct WorkflowConfiguration {
    // Human-readable workflow name (for display/logging)
    std::string name;

    // Schema version for future configuration evolution
    std::uint32_t version = 1;

    // Maximum number of Tasks in this Workflow.
    // 0 means unlimited (default).
    std::uint32_t maxTasks = 0;

    // Extension properties (future: key-value extension bag)
    // std::unordered_map<std::string, std::string> properties;
};

}  // namespace ak
