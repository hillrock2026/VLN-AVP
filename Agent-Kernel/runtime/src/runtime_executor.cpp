// ============================================================
// P0R0003 — Runtime Executor Implementation
// ============================================================
// Uses resolved ExecutionBinding from CapabilityResolver (P0R0004).
// Conforms to AK0032 and AK0033 execution flow alignment (ITL0004 B-02).

#include <runtime_executor.h>

#include <agent_kernel/task.hpp>

#include <any>
#include <string>

namespace ak::runtime {

Executor::Executor() = default;
Executor::~Executor() = default;

ak::ExecutionResult Executor::Execute(
    const ak::Task& task,
    const ak::ExecutionBinding& binding) {

    std::string validationError = ValidatePreconditions(task, binding);
    if (!validationError.empty()) {
        ak::ExecutionResult result;
        result.status = ak::ExecutionStatus::kFailed;
        result.message = validationError;
        result.retryable = false;
        return result;
    }


    std::string invocationOutput;
    ak::ExecutionStatus outcome = InvokeCapability(binding, invocationOutput);

    ak::ExecutionResult result;
    result.status = outcome;

    switch (outcome) {

        case ak::ExecutionStatus::kCompleted:
            result.message = "Execution completed successfully";
            // Real capability output (TASK 2 §16; TASK 3.1 §9.3):
            // the registered invoker's output, never a synthetic
            // completion string.
            result.output = std::any(std::move(invocationOutput));
            result.retryable = false;
            break;
        case ak::ExecutionStatus::kFailed:
            result.message = "Capability invocation failed";
            result.retryable = false;
            break;
        case ak::ExecutionStatus::kUnresolvable:
            result.message = "Capability could not be resolved";
            result.retryable = false;
            break;
        case ak::ExecutionStatus::kInternalError:
            result.message = "Unexpected Runtime internal error";
            result.retryable = false;
            break;
        case ak::ExecutionStatus::kCancelled:
            result.message = "Execution was cancelled";
            result.retryable = false;
            break;
        default:
            result.message = "Unknown execution outcome";
            result.retryable = false;
            break;
    }

    return result;
}

std::string Executor::ValidatePreconditions(
    const ak::Task& task,
    const ak::ExecutionBinding& binding) const noexcept {

    if (task.GetIDValue() == 0) {
        return "Task has invalid ID (zero)";
    }

    if (binding.capabilityID.name.empty()) {
        return "ExecutionBinding has empty capability name";
    }

    if (binding.status != ak::BindingStatus::kReady) {
        return "ExecutionBinding is not in kReady state";
    }

    return {};
}

ak::ExecutionStatus Executor::InvokeCapability(
    const ak::ExecutionBinding& binding,
    std::string& output) noexcept {

    // TASK 2 §16 / TASK 3.1 §9.3: real capability invocation.
    // The registered executable capability (invoker) is invoked
    // with the invocation payload; the invoker's output is the
    // real capability output. Synthetic success is removed.
    if (binding.status != ak::BindingStatus::kReady ||
        binding.capabilityID.name.empty()) {
        return ak::ExecutionStatus::kFailed;
    }

    if (!binding.invoker.has_value()) {
        // Registered capability name without an executable invoker:
        // deterministic failure, no silent synthetic success.
        return ak::ExecutionStatus::kFailed;
    }

    try {
        output = (*binding.invoker)(binding.payload.value_or(""));
        return ak::ExecutionStatus::kCompleted;
    } catch (...) {
        // An invoker failure is a deterministic execution failure.
        output.clear();
        return ak::ExecutionStatus::kFailed;
    }
}

}  // namespace ak::runtime
