// ============================================================
// Agent Kernel — TaskExecutionDescriptor
// ============================================================
// Describes WHAT execution capability a Task requires.
//
// TaskExecutionDescriptor is a pure description. It does
// NOT contain:
// - function pointers
// - callable objects / lambdas
// - callbacks
// - thread references
// - executor references
// - tool instances
// - plugin instances
// - any runtime mechanism
//
// The Executor (future AK0030+) resolves the actual
// execution capability through Runtime mechanisms —
// this descriptor only names what is needed.
//
// TaskExecutionDescriptor is a value type composed into
// Task. It is set during construction and read-only for
// the lifetime of the Task.
// ============================================================

#pragma once

#include <string>
#include <vector>
#include <cstdint>
#include <optional>

namespace ak {

// ============================================================
// ExecutionCapability — identifies what capability is needed
// ============================================================
// This is a logical name that the Runtime resolves to an
// actual execution mechanism. Examples:
//   "llm.chat"       → resolved to an LLM tool
//   "code.execute"   → resolved to a sandbox executor
//   "http.request"   → resolved to an HTTP client
//   "transform.json" → resolved to a data transform function
//
// The capability namespace is flat. Hierarchical naming
// is a convention (e.g., "category.name"), not a runtime
// hierarchy.
struct ExecutionCapability {
    // Logical name of the required capability.
    // Resolved by Runtime to an execution mechanism.
    std::string name;

    // Optional version constraint (e.g., ">=1.0,<2.0")
    // Resolved by Runtime capability registry.
    std::string versionConstraint;

    // Optional human-readable description
    std::string description;
};

// ============================================================
// TaskExecutionDescriptor — pure description of execution need
// ============================================================
struct TaskExecutionDescriptor {
    // The primary capability this Task requires.
    // Most Tasks require exactly one capability.
    ExecutionCapability capability;

    // Optional: runtime hints that do NOT affect execution
    // semantics. These are advisory only.
    // Examples:
    //   "priority": "high"
    //   "expectedDuration": "5s"
    //   "retryable": "true"
    std::vector<std::pair<std::string, std::string>> hints;

    // Schema version for future evolution
    std::uint32_t version = 1;
    // Optional: canonical invocation identity (TASK 2 §9.2;
    // TASK 3.1 §9.2). When set, the Runtime preserves this
    // identity on the per-invocation ExecutionResult so the
    // result can be retrieved by request_id.
    std::optional<std::string> request_id;

    // Optional: invocation payload (TASK 2 §9.4; TASK 3.1 §9.2).
    // Transported to the actual capability invocation boundary
    // without silent loss.
    std::optional<std::string> payload;

    // Future: fallback capabilities
    // std::vector<ExecutionCapability> fallbackCapabilities;

    // Future: resource requirements (e.g., memory, GPU)
    // struct ResourceRequirement { ... };
    // std::vector<ResourceRequirement> resourceRequirements;
};

}  // namespace ak
