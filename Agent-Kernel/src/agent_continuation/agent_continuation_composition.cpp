// ============================================================
// Agent Kernel - AgentContinuationComposition
// ============================================================
// TASK 3.5 implementation of the Agent-owned bounded
// continuation composition. Implements exactly one bounded
// continuation: first cycle (TASK 3.4 ExecuteOnce, reused
// unchanged) -> continuation precondition gate -> ONE
// continuation decision-generation (TASK 3.4 ExecuteOnce second
// call, reused unchanged) -> terminal -> STOP.
//
// The composition consumes only the existing Agent-facing
// surfaces (TASK 3.4 composition, Context, PromptAssemblyRequest);
// no Runtime internal type is included or referenced here.
// ============================================================

#include <agent_kernel/agent_continuation/agent_continuation_composition.hpp>

#include <string>
#include <utility>
#include <vector>

#include <agent_kernel/context/context_agent_contract.hpp>
#include <agent_kernel/context/context_objects.hpp>
#include <agent_kernel/context/context_services.hpp>
#include <agent_kernel/prompt/prompt_binding.hpp>

namespace ak::agent_continuation {
namespace {

// Deterministic TASK 3.3 evidence emitted only on the successful
// Runtime-backed tool path ("model:kToolInvoke;capability:...;
// context:updated"). kComplete / kInvalid never emit it.
const char* const kToolInvokeEvidence = "model:kToolInvoke";

// Deterministic marker outcome when the continuation does not
// start (PRE-1..PRE-4 not satisfied): bounded STOP, no
// synthetic next decision, no bypass.
ak::runtime_backed_agent::ExecutionCycleOutcome ContinuationNotStarted() {
    return ak::runtime_backed_agent::ExecutionCycleOutcome{
        false, ak::runtime_backed_agent::ExecutionTermination::kFailure,
        "continuation-not-started",
        "precondition:first-cycle-did-not-produce-observation-context-state"};
}

}  // namespace

AgentContinuationComposition::AgentContinuationComposition(
    ak::model_to_runtime::ModelToRuntimeDecisionComposition& model_to_runtime,
    ak::context::Context& context,
    ak::context::ContextObjectId context_object_id)
    : model_to_runtime_(model_to_runtime),
      context_(context),
      context_object_id_(context_object_id) {}

ContinuationOutcome AgentContinuationComposition::ExecuteBoundedContinuation(
    const ak::prompt::PromptAssemblyRequest& first_request) {
    ContinuationOutcome outcome;

    // PHASE 0: first cycle. Exactly one TASK 3.4 ExecuteOnce
    // (REUSED UNCHANGED).
    outcome.first_cycle = model_to_runtime_.ExecuteOnce(first_request);

    // PHASE 1: continuation precondition gate (PRE-1..PRE-4).
    // The continuation starts ONLY from a completed
    // observation/context state.
    if (!RequireContinuationPreconditions(outcome.first_cycle)) {
        outcome.continuation_started = false;
        outcome.continuation_cycle = ContinuationNotStarted();
        return outcome;  // bounded STOP
    }

    // PHASE 2: exactly ONE continuation decision-generation.
    // TASK 3.4 ExecuteOnce second call (REUSED UNCHANGED); the
    // input is built from the completed observation/context
    // state only.
    outcome.continuation_started = true;
    outcome.continuation_cycle =
        model_to_runtime_.ExecuteOnce(BuildContinuationInput(first_request));

    // PHASE 3: STOP. Any terminal result ends the bounded
    // continuation; no third decision, no loop, no retry.
    return outcome;
}

bool AgentContinuationComposition::RequireContinuationPreconditions(
    const ak::runtime_backed_agent::ExecutionCycleOutcome& first_cycle) const {
    // PRE-1 / R-1 / R-3: the first cycle must have reached
    // terminal kCompleted (Model failure / invalid / runtime
    // failure never satisfy the precondition).
    if (!first_cycle.completed ||
        first_cycle.termination !=
            ak::runtime_backed_agent::ExecutionTermination::kCompleted) {
        return false;
    }

    // PRE-2 / R-2: the completed cycle must have produced a
    // RuntimeObservation through the TASK 3.3 Runtime-backed
    // tool path. A kComplete decision (no Runtime invocation)
    // never emits the kToolInvoke evidence.
    if (first_cycle.diagnostics.find(kToolInvokeEvidence) ==
        std::string::npos) {
        return false;
    }

    // PRE-3 / PRE-4: the observation must have reached Agent
    // context; the Context object must contain the completed
    // observation/context state.
    const ak::context::ContextResultValue<ak::context::ContextObjectView> view =
        context_.AgentContract().Access().InspectObject(context_object_id_);
    return view.IsSuccess() && !view.value.content.empty();
}

ak::prompt::PromptAssemblyRequest
AgentContinuationComposition::BuildContinuationInput(
    const ak::prompt::PromptAssemblyRequest& first_request) const {
    // Continuation input is built ONLY from the completed
    // observation/context state (Context-derived material) and
    // the first request's declared variable surface. No new
    // variable is introduced (Prompt rejects unknown bindings)
    // and no external / synthetic material is injected.
    const ak::context::ContextResultValue<ak::context::ContextObjectView> view =
        context_.AgentContract().Access().InspectObject(context_object_id_);
    const std::string observation_material =
        view.IsSuccess() ? view.value.content : std::string{};

    std::vector<ak::prompt::PromptInputBinding> bindings;
    bindings.reserve(first_request.Bindings().size());
    for (const ak::prompt::PromptInputBinding& binding :
         first_request.Bindings()) {
        std::string value = binding.Value();
        if (!observation_material.empty()) {
            if (!value.empty()) {
                value.push_back(' ');
            }
            value += "[completed observation: " + observation_material + "]";
        }
        bindings.emplace_back(binding.VariableName(), std::move(value));
    }
    return ak::prompt::PromptAssemblyRequest(std::move(bindings),
                                             first_request.Metadata());
}

}  // namespace ak::agent_continuation
