// ============================================================
// Agent Kernel - ExecutionContext
// ============================================================
// Runtime-only value object scoped to a single execution.
//
// ExecutionContext carries runtime metadata, cancellation
// signals, and configuration for one execution.
// It exists only during execution and is NOT stored in Task.
//
// AK0022 Chapter 4.2 - ExecutionContext
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <unordered_map>

#include <agent_kernel/object_id.hpp>

namespace ak {

// ============================================================
// ExecutionID - unique identifier for one execution
// ============================================================
class ExecutionID : public KernelObjectID {
    using KernelObjectID::KernelObjectID;
};

// ============================================================
// ExecutionContext
// ============================================================
struct ExecutionContext {
    // Unique identifier for this execution
    ExecutionID executionID;

    // Source identifiers
    WorkflowID workflowID;
    TaskID taskID;

    // Reserved for future:
    // CancellationToken cancellationToken;
    // std::chrono::milliseconds timeout;
    // std::vector<std::string> tracingContext;
};

}  // namespace ak
