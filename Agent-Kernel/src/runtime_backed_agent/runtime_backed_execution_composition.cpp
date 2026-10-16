// ============================================================
// Agent Kernel - RuntimeBackedExecutionComposition
// ============================================================
// TASK 3.3 implementation of the Agent-owned bounded execution
// composition. Implements exactly the bounded synchronous step
// proven by TASK 3.2 (tests/runtime_integration/): one Agent
// decision -> zero or one Runtime invocation -> one resulting
// observation -> one Context update -> terminal state.
//
// The composition consumes only the Agent-owned
// RuntimeInteractionPort; no Runtime internal type is included
// or referenced here.
// ============================================================

#include <agent_kernel/runtime_backed_agent/runtime_backed_execution_composition.hpp>

#include <string>
#include <utility>

#include <agent_kernel/context/context_agent_contract.hpp>
#include <agent_kernel/context/context_objects.hpp>
#include <agent_kernel/context/context_services.hpp>

namespace ak::runtime_backed_agent {
namespace {

ExecutionCycleOutcome FailureOutcome(std::string diagnostics) {
    return ExecutionCycleOutcome{
        false, ExecutionTermination::kFailure,
        "runtime-backed-cycle-failure", std::move(diagnostics)};
}

}  // namespace

RuntimeBackedExecutionComposition::RuntimeBackedExecutionComposition(
    ak::agent::RuntimeInteractionPort& port,
    ak::context::Context& context,
    ak::context::ContextObjectId context_object_id)
    : port_(port),
      context_(context),
      context_object_id_(context_object_id) {}

ExecutionCycleOutcome RuntimeBackedExecutionComposition::Execute(
    const ak::agent::ModelAction& decision) {
    // kComplete: terminal success without Runtime invocation
    // (TASK 3.3 Contract 14; T3.3-AC-015).
    if (decision.IsComplete()) {
        return ExecutionCycleOutcome{
            true, ExecutionTermination::kCompleted,
            "runtime-backed-cycle-completed", "model:kComplete"};
    }

    // kInvalid: deterministic invalid terminal without Runtime
    // invocation (TASK 3.3 Contract 15; T3.3-AC-016).
    if (decision.IsInvalid()) {
        return ExecutionCycleOutcome{
            false, ExecutionTermination::kInvalid,
            "runtime-backed-cycle-invalid",
            "model:kInvalid;reason:" + decision.Reason()};
    }

    // kToolInvoke: one bounded Runtime invocation through the
    // sanctioned port (TASK 3.3 Contract 9/10/19).
    if (!decision.IsToolInvoke() || decision.Capability() == nullptr) {
        return FailureOutcome("invalid-tool-invocation");
    }
    return InvokeTool(decision);
}

ExecutionCycleOutcome RuntimeBackedExecutionComposition::InvokeTool(
    const ak::agent::ModelAction& action) {
    // 1. Build the RuntimeInvocationRequest from the Agent
    //    decision. request_id is the canonical per-invocation
    //    identity (TASK 2 9; F-003 CLOSED). The identity is
    //    seeded from the Agent-owned Context identity plus a
    //    per-composition counter so each invocation is
    //    deterministic and unique across compositions (no
    //    request-A / request-B cross-talk; T3.3-AC-009).
    const std::string request_id =
        "runtime-backed-invocation-" +
        context_.GetIdentity().ToString() + "-" +
        std::to_string(++invocation_counter_);
    const ak::agent::RuntimeRequestId runtime_request_id(request_id);
    const ak::agent::RuntimeInvocationRequest request{
        runtime_request_id, action.Capability()->Value(),
        action.Arguments()};

    // 2. Submit through the sanctioned Agent-facing port. The
    //    concrete RuntimePublicApiAdapter performs the Runtime
    //    interaction (A1 capability translation, payload
    //    transport, real invocation).
    const ak::agent::RuntimeSubmissionResult submission = port_.Submit(request);

    // 3. Observe the per-invocation outcome for the SAME
    //    request_id (T3.3-AC-009). The composition interprets
    //    the RuntimeObservation for both success and failure
    //    (Contract 12/13: RuntimeObservation -> Context Update
    //    -> terminal state). The adapter maps rejected and
    //    failed submissions to the same deterministic failure
    //    observation.
    const ak::agent::RuntimeObservation observation =
        port_.Observe(runtime_request_id);

    // 4. Apply the observation to Context through the existing
    //    ContextAgentContract::Update: success output on
    //    success, deterministic failure evidence on failure
    //    (Contract 12/13; T3.3-AC-010/011/012/013/014).
    if (!ApplyObservation(observation)) {
        return FailureOutcome("context-update-failed");
    }

    // 5. Terminal decision: the composition classifies the
    //    observation outcome. No synthetic success, no retry,
    //    no recovery (Contract 13).
    if (observation.status == ak::agent::ObservationStatus::kSuccess) {
        return ExecutionCycleOutcome{
            true, ExecutionTermination::kCompleted,
            "runtime-backed-cycle-completed",
            "model:kToolInvoke;capability:" + request.capability_id +
                ";context:updated"};
    }

    const std::string failure =
        observation.failure.empty() ? submission.failure
                                    : observation.failure;
    return FailureOutcome(
        failure.empty() ? ("observation-failed:" + request_id) : failure);
}
bool RuntimeBackedExecutionComposition::ApplyObservation(
    const ak::agent::RuntimeObservation& observation) {
    ak::context::ContextAgentContract& contract = context_.AgentContract();
    ak::context::ContextUpdateService& update = contract.Update();
    if (!update.BeginUpdate(context_object_id_).IsSuccess()) {
        return false;
    }
    const std::string content =
        (observation.status == ak::agent::ObservationStatus::kSuccess)
            ? observation.output
            : observation.failure;
    if (!update.ApplyUpdate(context_object_id_, content,
                            ak::context::ContextMetadata{})
             .IsSuccess()) {
        return false;
    }
    return update.CompleteUpdate(context_object_id_).IsSuccess();
}

}  // namespace ak::runtime_backed_agent
