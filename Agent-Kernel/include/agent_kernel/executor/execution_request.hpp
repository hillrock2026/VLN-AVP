// ============================================================
// Agent Kernel - ExecutionRequest
// ============================================================
// Runtime value object representing a request to execute.
//
// ExecutionRequest packages all data needed for a single
// execution. It does NOT contain Core Domain pointers.
//
// AK0022 Chapter 4.1 - ExecutionRequest
// ============================================================

#pragma once

#include <agent_kernel/object_id.hpp>
#include <agent_kernel/task/task_execution_descriptor.hpp>
#include <agent_kernel/executor/execution_context.hpp>

namespace ak {

// ============================================================
// ExecutionRequest
// ============================================================
struct ExecutionRequest {
    TaskID taskID;
    WorkflowID workflowID;
    TaskExecutionDescriptor descriptor;
    ExecutionContext context;
};

}  // namespace ak
