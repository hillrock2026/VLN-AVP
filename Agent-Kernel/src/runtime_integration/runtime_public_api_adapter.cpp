// ============================================================
// Agent Kernel - RuntimePublicApiAdapter implementation
// ============================================================
// TASK 2 §13 / TASK 3.1 §17 (Invocation Flow) / §18 (Result
// Flow) / §19 (Failure Flow).
//
// This translation unit is the ONLY production code that links
// the Runtime: the adapter translates Agent-owned integration
// values into Runtime Public API calls and maps every Runtime
// outcome back to Agent-owned values. No Runtime internal type
// crosses the Agent boundary.
//
// A1: capability identity translation happens here
//     (request.capability_id -> descriptor.capability.name).
// B1: Submit/Observe overrides are the only Runtime interaction.
// ============================================================

#include <agent_kernel/runtime_integration/runtime_public_api_adapter.hpp>
#include <agent_kernel/runtime_integration/runtime_execution_authority.hpp>

#include <any>
#include <cctype>
#include <memory>
#include <string>
#include <utility>

#include <runtime.h>

#include <agent_kernel/session.hpp>
#include <agent_kernel/session/session_builder.hpp>
#include <agent_kernel/task.hpp>
#include <agent_kernel/task/task_execution_descriptor.hpp>
#include <agent_kernel/workflow.hpp>

namespace ak::runtime_integration {

namespace {

bool IsBlank(const std::string& value) noexcept {
    for (const char c : value) {
        if (!std::isspace(static_cast<unsigned char>(c))) {
            return false;
        }
    }
    return true;
}

ak::agent::RuntimeSubmissionResult Reject(
    const ak::agent::RuntimeRequestId& request_id,
    std::string reason) {
    return ak::agent::RuntimeSubmissionResult{
        request_id, false, ak::agent::SubmissionStatus::kRejected,
        std::move(reason)};
}

ak::agent::RuntimeSubmissionResult FailSubmission(
    const ak::agent::RuntimeRequestId& request_id,
    std::string reason) {
    return ak::agent::RuntimeSubmissionResult{
        request_id, true, ak::agent::SubmissionStatus::kFailed,
        std::move(reason)};
}

ak::agent::RuntimeObservation FailureObservation(
    const ak::agent::RuntimeRequestId& request_id,
    const std::string& capability_id,
    std::string reason) {
    return ak::agent::RuntimeObservation{
        request_id, capability_id, ak::agent::ObservationStatus::kFailure,
        "", std::move(reason)};
}

}  // namespace

RuntimePublicApiAdapter::RuntimePublicApiAdapter(
    ak::runtime::Runtime& runtime) noexcept
    : runtime_(runtime) {}

// K0-BLOCKER-REMEDIATION-05 (INV-K0-FWA-RUNTIME-AUTHORITY): the only
// production issuance of the Kernel execution authority. Every issued
// handle is bound to a real RuntimePublicApiAdapter constructed from
// a real Kernel Runtime; no other construction path exists.
RuntimeExecutionAuthorityHandle IssueRuntimeExecutionAuthority(
    ak::runtime::Runtime& runtime) {
    return RuntimeExecutionAuthorityHandle(
        std::unique_ptr<ak::agent::RuntimeInteractionPort>(
            std::make_unique<RuntimePublicApiAdapter>(runtime)));
}

void RuntimePublicApiAdapter::RegisterCapability(
    std::string name,
    std::string provider,
    std::function<std::string(const std::string&)> invoker) {
    RegisteredCapability capability{
        std::move(provider), std::move(invoker)};
    capabilities_[std::move(name)] = std::move(capability);
}

ak::agent::RuntimeSubmissionResult RuntimePublicApiAdapter::Submit(
    const ak::agent::RuntimeInvocationRequest& request) {
    const std::string request_id = request.request_id.Value();
    const std::string capability_id = request.capability_id;

    // ------------------------------------------------------------
    // 1. Adapter pre-validation (TASK 3.1 §19): invalid invocation
    //    (empty capability_id / payload) -> rejected before Runtime.
    // ------------------------------------------------------------
    if (capability_id.empty() || IsBlank(capability_id) ||
        IsBlank(request.payload)) {
        const std::string reason =
            "invalid-invocation: capability_id and payload "
            "must be non-empty";
        submission_failures_[request_id] = reason;
        return Reject(request.request_id, reason);
    }

    // ------------------------------------------------------------
    // 2. Bootstrap capability registration (TASK 3.1 §17): the
    //    adapter ensures the capability is available through the
    //    sanctioned Runtime::RegisterCapability path before Run.
    // ------------------------------------------------------------
    const auto it = capabilities_.find(capability_id);
    if (it != capabilities_.end() &&
        !runtime_.HasCapability(capability_id)) {
        runtime_.RegisterCapability(capability_id, it->second.provider,
                                    it->second.invoker);
    }

    // ------------------------------------------------------------
    // 3. Capability not available -> deterministic failure
    //    (TASK 3.1 §19: capability-not-found:<name>).
    // ------------------------------------------------------------
    if (!runtime_.HasCapability(capability_id)) {
        const std::string reason =
            "capability-not-found:" + capability_id;
        submission_failures_[request_id] = reason;
        return FailSubmission(request.request_id, reason);
    }

    // ------------------------------------------------------------
    // 4. Translate one RuntimeInvocationRequest into a minimal
    //    Session -> Workflow -> single-Task graph carrying
    //    request_id + capability_id + payload (TASK 2 §13.4;
    //    TASK 3.1 §17). These Runtime objects stay behind the
    //    Runtime Public API boundary and never become Agent-facing
    //    contract types.
    //
    //    A1 translation point (exact, sole identity translation):
    //        request.capability_id -> descriptor.capability.name
    // ------------------------------------------------------------
    ak::TaskExecutionDescriptor descriptor;
    descriptor.capability.name = capability_id;
    descriptor.request_id = request_id;
    descriptor.payload = request.payload;

    auto session = ak::SessionBuilder()
        .WithID(ak::SessionID(
            static_cast<ak::SessionID::ValueType>(session_counter_ + 1)))
        .WithName("runtime-integration-invocation")
        .WithMaxWorkflows(1)
        .Build();
    session->Initialize();
    session->Activate();

    const ak::WorkflowID workflow_id = session->CreateWorkflow();
    ak::Workflow* workflow = session->FindWorkflow(workflow_id);
    if (workflow == nullptr) {
        return FailSubmission(request.request_id,
                              "runtime-internal-error: workflow creation failed");
    }
    workflow->AddTask(descriptor);
    workflow->Validate();
    ++session_counter_;

    // ------------------------------------------------------------
    // 5. Submit through the Runtime Public API (TASK 2 §13.2.6).
    // ------------------------------------------------------------
    const ak::runtime::RuntimeResult result = runtime_.Run(*session);

    // ------------------------------------------------------------
    // 6. Terminal submission outcome (TASK 2 §10 / F-002 CLOSED):
    //    submit -> completed | rejected | failed.
    // ------------------------------------------------------------
    if (result.IsSuccess()) {
        // Preserve capability identity for the later Observe mapping.
        submitted_capabilities_[request_id] = capability_id;
        return ak::agent::RuntimeSubmissionResult{
            request.request_id, true,
            ak::agent::SubmissionStatus::kCompleted, ""};
    }

    const std::string reason =
        (result.status == ak::runtime::RuntimeStatus::kInternalError)
        ? std::string("runtime-internal-error")
        : ("capability-invocation-failed:" + capability_id);
    submission_failures_[request_id] = reason;
    return FailSubmission(request.request_id, reason);
}

ak::agent::RuntimeObservation RuntimePublicApiAdapter::Observe(
    const ak::agent::RuntimeRequestId& request_id) {
    const std::string id = request_id.Value();

    // ------------------------------------------------------------
    // Per-invocation result retrieval (TASK 2 §17; TASK 3.1 §9.4):
    // request_id -> specific invocation -> specific ExecutionResult.
    // ------------------------------------------------------------
    const auto it = submitted_capabilities_.find(id);
    const std::string capability_id =
        (it != submitted_capabilities_.end()) ? it->second : "";

    // Failures that terminated before/without a stored Runtime
    // per-invocation result (rejected / pre-Run failed) map to
    // the same deterministic reason (TASK 3.1 §19).
    const auto fail_it = submission_failures_.find(id);
    if (fail_it != submission_failures_.end()) {
        return FailureObservation(request_id, capability_id,
                                  fail_it->second);
    }

    // ------------------------------------------------------------
    // Per-invocation result retrieval (TASK 2 §17; TASK 3.1 §9.4):
    // request_id -> specific invocation -> specific ExecutionResult.
    // ------------------------------------------------------------
    const std::optional<ak::ExecutionResult> result =
        runtime_.GetInvocationResult(id);
    if (!result.has_value()) {
        // Result retrieval failure (TASK 3.1 §19:
        // result-not-found:<request_id>).
        return FailureObservation(request_id, capability_id,
                                  "result-not-found:" + id);
    }

    if (result->IsSuccess()) {
        if (!result->output.has_value()) {
            return FailureObservation(
                request_id, capability_id,
                "capability-invocation-failed:" + capability_id);
        }
        try {
            const std::string output =
                std::any_cast<std::string>(result->output.value());
            return ak::agent::RuntimeObservation{
                request_id, capability_id,
                ak::agent::ObservationStatus::kSuccess, output, ""};
        } catch (const std::bad_any_cast&) {
            return FailureObservation(
                request_id, capability_id,
                "capability-invocation-failed:" + capability_id);
        }
    }

    // Execution failure (missing invoker / invoker failure /
    // resolution failure) -> deterministic failure observation
    // (TASK 3.1 §19: capability-invocation-failed:<name>).
    return FailureObservation(request_id, capability_id,
                              "capability-invocation-failed:" + capability_id);
}

}  // namespace ak::runtime_integration