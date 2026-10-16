#pragma once

// ============================================================
// P0R0003 — Runtime Executor
// ============================================================
// The Executor executes a Task through the Capability
// infrastructure and returns execution evidence to Runtime.
//
// Responsibilities:
// - Validate execution preconditions
// - Obtain TaskExecutionDescriptor from Task
// - Invoke Capability through CapabilityResolver (P0R0004)
// - Collect execution outcome
// - Construct canonical ExecutionResult
//
// NON-responsibilities:
// - Does NOT schedule Tasks (Scheduler — P0R0002)
// - Does NOT resolve Capabilities (Resolver — P0R0004)
// - Does NOT publish Events (EventBus — P0R0005)
// - Does NOT modify Runtime lifecycle
//
// Conforms to AK0032 (Runtime Executor Specification).
// ============================================================

#include <string>

#include <agent_kernel/executor/execution_result.hpp>
#include <agent_kernel/runtime/capability/execution_binding.hpp>
#include <agent_kernel/task/task_execution_descriptor.hpp>

namespace ak {

class Task;

}  // namespace ak

namespace ak::runtime {

// Forward declaration.
class CapabilityResolver;

// ============================================================
// Executor — Runtime execution component (Revision 2, P0R0003)
// ============================================================
// Synchronous, single-threaded, invocation-only component.
//
// Usage:
//   Executor executor;
//   auto binding = resolver.Resolve(descriptor);
//   auto result = executor.Execute(task, binding);
class Executor {
public:
    Executor();
    ~Executor();

    Executor(const Executor&) = delete;
    Executor& operator=(const Executor&) = delete;
    Executor(Executor&&) = delete;
    Executor& operator=(Executor&&) = delete;

    // ---- Execution ----
    // Execute one Task with its resolved ExecutionBinding.
    // Binding MUST come from CapabilityResolver::Resolve().
    // Returns exactly one ExecutionResult per invocation.
    // Synchronous; no concurrent invocation.
    [[nodiscard]] ak::ExecutionResult Execute(
        const ak::Task& task,
        const ak::ExecutionBinding& binding);

private:
    // Validate that task and binding satisfy execution preconditions.
    // Returns empty string on success, or diagnostic on failure.
    [[nodiscard]] std::string ValidatePreconditions(
        const ak::Task& task,
        const ak::ExecutionBinding& binding) const noexcept;


    // Capability invocation (TASK 2 §16; TASK 3.1 §9.3).
    // Invokes the registered executable capability (invoker) with
    // the binding payload; on success `output` carries the real
    // capability output. Missing invoker or invoker failure yields
    // kFailed deterministically. Exceptions never escape.
    [[nodiscard]] static ak::ExecutionStatus InvokeCapability(
        const ak::ExecutionBinding& binding,
        std::string& output) noexcept;
};

}  // namespace ak::runtime
