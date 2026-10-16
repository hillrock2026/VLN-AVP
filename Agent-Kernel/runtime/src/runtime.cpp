// ============================================================
// P0R0006 — Runtime Integration (Walking Skeleton)
// ============================================================
// Integrates the frozen Runtime Revision 2 components into a
// single end-to-end execution path:
//
//   Runtime startup → initialization → Session creation →
//   Workflow creation → Task creation → Scheduler selection →
//   Capability resolution → Task execution → Event publication →
//   Task/Workflow/Session completion → Runtime shutdown (Stop).
//
// Orchestration responsibilities (AK0035):
//   - Request scheduling decisions from the Scheduler.
//   - Retrieve the immutable TaskExecutionDescriptor from the Task.
//   - Resolve the descriptor through the CapabilityResolver.
//   - Invoke the Executor with the resolved binding.
//   - Evaluate ExecutionResult and request Core lifecycle transitions.
//   - Publish Runtime events through the EventBus.
//
// Conforms to AK0030-I4 (Runtime Public API Specification) and
// preserves the frozen Runtime Revision 2 architecture.
// ============================================================

#include <runtime.h>
#include <agent_kernel/session.hpp>
#include <agent_kernel/workflow.hpp>
#include <agent_kernel/task.hpp>
#include <agent_kernel/runtime/capability/execution_binding.hpp>
#include <stdexcept>
#include <string>
#include <utility>
#include <utility>

namespace ak::runtime {
namespace {

// ============================================================
// Bridge a resolved CapabilityBinding into the canonical
// ExecutionBinding consumed by the Executor.
// ============================================================
// AK0033 §8.2: Resolve() returns CapabilityBinding (providerName).
// AK0032:     Executor consumes a resolved binding; capability
//             resolution is performed by Runtime before invocation.
ak::ExecutionBinding BuildExecutionBinding(
    const ak::CapabilityBinding& capabilityBinding,
    const ak::TaskExecutionDescriptor& descriptor) {

    ak::ExecutionBinding binding;
    binding.capabilityID.name = descriptor.capability.name;

    binding.capabilityID.provider = capabilityBinding.providerName;
    binding.payload = descriptor.payload;
    binding.invoker = capabilityBinding.invoker;
    binding.status = ak::BindingStatus::kReady;
    return binding;
}

}  // namespace

Runtime::Runtime()
    : stateMachine_()
    , lifecycleManager_(stateMachine_)
    , running_(false) {}

Runtime::~Runtime() = default;

RuntimeResult Runtime::Run(ak::Session& session) {
    // AK0035 §7.9 / §17.5 — complete Runtime public exception boundary.
    // Unexpected implementation exceptions are intercepted within the
    // Runtime implementation and translated into RuntimeResult objects;
    // they never escape through the Runtime Public API.
    try {
        if (stateMachine_.GetState() != RuntimeState::kCreated) {
            RuntimeResult result;
            result.status = RuntimeStatus::kInternalError;
            result.message = "Runtime is not in kCreated state";
            return result;
        }

        if (session.GetState() != ak::KernelObjectState::kReady) {
            RuntimeResult result;
            result.status = RuntimeStatus::kInvalidSession;
            result.message = "Session is not in an executable lifecycle state";
            return result;
        }

        if (!lifecycleManager_.Initialize()) {
            RuntimeResult result;
            result.status = RuntimeStatus::kInternalError;
            result.message = "Runtime initialization failed";
            return result;
        }


        running_ = true;

        // Per-invocation result store is scoped to the current
        // Run (TASK 3.1 §9.4): cleared at the start of each Run.
        invocationResults_.clear();

        // CAP0006-002 test seam — deterministic verification of
        // the public exception boundary. Only armed by the Runtime test
        // suite; normal production execution never arms it.
        if (injectFailureForTesting_) {
            injectFailureForTesting_ = false;
            throw std::runtime_error(
                "CAP0006-002: injected unexpected implementation failure");
        }

        // ---- P0R0006: canonical Walking Skeleton execution flow ----

        const ak::SessionID sessionId = session.GetID();

        // Session started event (AK0034 §10).
        PublishRuntimeEvent(ak::RuntimeEventType::kSessionStarted,
                            ak::TaskID(), ak::WorkflowID(), sessionId,
                            "session started");

        RuntimeResult result;
        result.status = RuntimeStatus::kCompleted;
        result.message = "Runtime completed";

        // Execute every Workflow owned by the Session (canonical lifecycle:
        // Created → Initialized → Ready → Running).
        for (const ak::WorkflowID workflowId : session.Workflows().Enumerate()) {
            ak::Workflow* workflow = session.FindWorkflow(workflowId);
            if (workflow == nullptr) {
                continue;
            }

            workflow->Initialize();
            workflow->Activate();
            workflow->Start();

            // Each Workflow owns an independent TaskID space (Task IDs restart
            // per Workflow). Scheduling state is therefore scoped per Workflow via
            // an equivalent Scheduler instance (AK0031 §6.2) — the frozen Scheduler
            // component remains unchanged.
            Scheduler workflowScheduler;
            workflowScheduler.Attach(workflowId);
            result.workflowsTotal++;

            // Workflow started event.
            PublishRuntimeEvent(ak::RuntimeEventType::kWorkflowStarted,
                                ak::TaskID(), workflowId, sessionId,
                                "workflow started");

            bool workflowCompleted = true;

            // Deterministic execution loop (AK0035):
            //   Scheduler selects → Resolver resolves → Executor executes →
            //   Runtime notifies → repeat until workflow completion.
            while (true) {
                const SchedulingDecision decision =
                    workflowScheduler.Next(workflow->Graph());

                if (decision.status == SchedulingStatus::kWorkflowCompleted) {
                    break;
                }

                if (decision.status == SchedulingStatus::kWorkflowFailed ||
                    decision.status == SchedulingStatus::kNoRunnableTask ||
                    !decision.HasTask()) {
                    workflowCompleted = false;
                    break;
                }

                ak::Task* task = workflow->FindTask(*decision.nextTask);
                if (task == nullptr) {
                    workflowCompleted = false;
                    break;
                }

                result.tasksTotal++;

                const ak::TaskID taskId = task->GetID();

                // Task started event.
                PublishRuntimeEvent(ak::RuntimeEventType::kTaskStarted,
                                    taskId, workflowId, sessionId,
                                    "task started");

                // Descriptor retrieval — Task remains the sole owner of its
                // TaskExecutionDescriptor (AK0032 §3.4).
                const ak::TaskExecutionDescriptor& descriptor =
                    task->GetExecutionDescriptor();

                // Capability resolution — exclusively through the
                // CapabilityResolver (AK0033 §7.2).
                bool resolutionSucceeded = true;
                ak::ExecutionBinding executionBinding;
                try {
                    const ak::CapabilityBinding capabilityBinding =
                        resolver_.Resolve(descriptor);
                    executionBinding =
                        BuildExecutionBinding(capabilityBinding, descriptor);
                } catch (const std::runtime_error&) {
                    resolutionSucceeded = false;
                }

                if (!resolutionSucceeded) {
                    workflowScheduler.NotifyFailed(taskId);
                    result.tasksFailed++;
                    PublishRuntimeEvent(ak::RuntimeEventType::kTaskFailed,
                                        taskId, workflowId, sessionId,
                                        "task failed");
                    workflowCompleted = false;
                    break;
                }

                // Task execution — exclusively through the Executor (AK0032).

                ak::ExecutionResult executionResult =
                    executor_.Execute(*task, executionBinding);

                // Preserve the canonical invocation identity on the
                // per-invocation result (TASK 2 §9.2 / §17; F-003
                // CLOSED) and store it for retrieval.
                executionResult.request_id = descriptor.request_id;
                if (descriptor.request_id.has_value()) {
                    invocationResults_[*descriptor.request_id] =
                        executionResult;
                }

                if (executionResult.IsSuccess()) {
                    task->Complete();
                    workflowScheduler.NotifyCompleted(taskId);
                    result.tasksCompleted++;
                    PublishRuntimeEvent(ak::RuntimeEventType::kTaskCompleted,
                                        taskId, workflowId, sessionId,
                                        "task completed");
                } else {
                    workflowScheduler.NotifyFailed(taskId);
                    result.tasksFailed++;
                    PublishRuntimeEvent(ak::RuntimeEventType::kTaskFailed,
                                        taskId, workflowId, sessionId,
                                        "task failed");
                    workflowCompleted = false;
                    break;
                }
            }

            if (workflowCompleted) {
                workflow->Complete();
                result.workflowsCompleted++;
                PublishRuntimeEvent(ak::RuntimeEventType::kWorkflowCompleted,
                                    ak::TaskID(), workflowId, sessionId,
                                    "workflow completed");
            } else {
                workflow->Cancel();
                result.workflowsFailed++;
                PublishRuntimeEvent(ak::RuntimeEventType::kWorkflowFailed,
                                    ak::TaskID(), workflowId, sessionId,
                                    "workflow failed");
            }

            workflowScheduler.Detach(workflowId);
        }

        // Session completion — Runtime requests the Core lifecycle
        // transition (AK0035 §2.2 Lifecycle Coordination).
        session.Shutdown();

        // Session completed event.
        PublishRuntimeEvent(ak::RuntimeEventType::kSessionCompleted,
                            ak::TaskID(), ak::WorkflowID(), sessionId,
                            "session completed");

        if (result.workflowsFailed > 0 || result.tasksFailed > 0) {
            result.status = RuntimeStatus::kFailed;
            result.message = "Runtime completed with failures";
        }

        return result;
    } catch (...) {
        // Unexpected internal Runtime failure (AK0035 §17.5): terminate
        // execution safely and represent the outcome as kInternalError.
        lifecycleManager_.Fail(
            "Runtime execution failed due to an unexpected internal error");
        running_ = false;

        RuntimeResult failure;
        failure.status = RuntimeStatus::kInternalError;
        failure.message =
            "Runtime execution failed due to an unexpected internal error";
        return failure;
    }
}

void Runtime::Stop() {
    if (!running_) return;
    running_ = false;
    lifecycleManager_.Shutdown();
}

bool Runtime::IsRunning() const noexcept {
    return running_;
}

// ---- Component Access ----
// Scheduler (P0R0002), Executor (P0R0003),
// CapabilityResolver (P0R0004), EventBus (P0R0005).

Scheduler& Runtime::GetScheduler() noexcept { return scheduler_; }
Executor& Runtime::GetExecutor() noexcept { return executor_; }
CapabilityResolver& Runtime::GetResolver() noexcept { return resolver_; }

EventBus& Runtime::GetEventBus() noexcept { return eventBus_; }

// ============================================================
// TASK 2 CC-4a Minimum Runtime Public API Extensions
// ============================================================

void Runtime::RegisterCapability(const std::string& name,
                                 const std::string& provider,
                                 ak::CapabilityInvoker invoker) {
    resolver_.Register(name, provider, invoker);
}

bool Runtime::HasCapability(const std::string& name) const {
    return resolver_.Contains(name);
}

std::optional<ak::ExecutionResult> Runtime::GetInvocationResult(
    const std::string& request_id) const {
    const auto it = invocationResults_.find(request_id);
    if (it == invocationResults_.end()) {
        return std::nullopt;
    }
    return it->second;
}

// ============================================================
// Event publication — canonical Runtime event propagation
// ============================================================
void Runtime::PublishRuntimeEvent(ak::RuntimeEventType type,
                                  const ak::TaskID& taskId,
                                  const ak::WorkflowID& workflowId,
                                  const ak::SessionID& sessionId,
                                  std::string message) {
    ak::RuntimeEvent event;
    event.type = type;
    event.taskID = taskId;
    event.workflowID = workflowId;
    event.sessionID = sessionId;
    event.message = std::move(message);
    eventBus_.Publish(event);
}

}  // namespace ak::runtime
