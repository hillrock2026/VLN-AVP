// ============================================================
// model_to_runtime_decision_composition.cpp - TASK 3.4
// ============================================================
// Agent-owned one-bounded-cycle Model-to-Runtime decision
// integration (TASK 3.4 Contract sections 5-9; Implementation
// Plan sections 10, 12, 14).
//
// M-001: ModelResult::kFailure is intercepted by the
// composition Status() gate immediately after Infer() and
// BEFORE InterpretModelResult / ModelAction generation /
// RuntimeBackedExecutionComposition::Execute():
//   kFailure -> terminal kFailure
//   NO InterpretModelResult, NO ModelAction (no kInvalid
//   conversion), NO Execute(), NO Runtime invocation, NO
//   synthetic success, NO retry, NO second cycle.
// ============================================================

#include <agent_kernel/model_to_runtime/model_to_runtime_decision_composition.hpp>

#include <algorithm>
#include <cctype>
#include <string>
#include <utility>

#include <agent_kernel/model/model_result.hpp>
#include <agent_kernel/model_to_runtime/model_result_interpreter.hpp>

namespace ak::model_to_runtime {
namespace {

// Deterministic blank check: empty or whitespace-only material
// cannot be translated into a valid ModelInput (ModelInput
// construction rejects it with std::invalid_argument).
bool IsBlank(const std::string& content) noexcept {
    return std::all_of(content.begin(), content.end(),
                       [](unsigned char c) { return std::isspace(c) != 0; });
}

// Deterministic provider-neutral error category name (P1-IS008
// Chapter 14), used so the Model-side failure diagnostic and
// error category remain observable at the terminal outcome.
const char* ErrorCategoryName(ak::model::ModelErrorCategory category) noexcept {
    switch (category) {
        case ak::model::ModelErrorCategory::kNone:
            return "none";
        case ak::model::ModelErrorCategory::kInvalidInput:
            return "invalid-input";
        case ak::model::ModelErrorCategory::kModelFailure:
            return "model-failure";
        case ak::model::ModelErrorCategory::kInvalidResult:
            return "invalid-result";
    }
    return "unknown";
}

}  // namespace

ModelToRuntimeDecisionComposition::ModelToRuntimeDecisionComposition(
    ak::agent::AgentPromptBinding& prompt_binding,
    ak::agent::AgentModelBinding& model_binding,
    ak::runtime_backed_agent::RuntimeBackedExecutionComposition&
        runtime_composition)
    : prompt_binding_(prompt_binding),
      model_binding_(model_binding),
      runtime_composition_(runtime_composition) {}

ak::runtime_backed_agent::ExecutionCycleOutcome
ModelToRuntimeDecisionComposition::ExecuteOnce(
    const ak::prompt::PromptAssemblyRequest& request) {
    // Step 1: one Prompt assembly -> one ModelInput.
    std::string failure_diagnostic;
    const std::optional<ak::model::ModelInput> input =
        AssembleModelInput(request, failure_diagnostic);
    if (!input.has_value()) {
        return {false,
                ak::runtime_backed_agent::ExecutionTermination::kFailure,
                "prompt-assembly-failure", failure_diagnostic};
    }

    // Steps 2-4: one inference, one Status() gate (M-001), one
    // interpretation.
    const std::optional<ak::agent::ModelAction> action =
        InferAndInterpret(*input, failure_diagnostic);
    if (!action.has_value()) {
        // ModelResult::kFailure at the Status() gate (M-001):
        // terminal kFailure, NO ModelAction, NO Execute, NO
        // Runtime invocation, NO synthetic success, NO retry,
        // NO second cycle.
        return {false,
                ak::runtime_backed_agent::ExecutionTermination::kFailure,
                "model-inference-failure", failure_diagnostic};
    }

    // Step 5: hand the Agent-owned ModelAction to the CLOSED
    // TASK 3.3 composition (REUSED UNCHANGED). kToolInvoke is
    // the only path that reaches the Runtime; kComplete /
    // kInvalid terminate inside the TASK 3.3 composition
    // without any Runtime invocation.
    return runtime_composition_.Execute(*action);
}

std::optional<ak::model::ModelInput>
ModelToRuntimeDecisionComposition::AssembleModelInput(
    const ak::prompt::PromptAssemblyRequest& request,
    std::string& failure_diagnostic) {
    const ak::prompt::PromptAssemblyResult assembly =
        prompt_binding_.Assemble(request);
    if (!assembly.Succeeded() || !assembly.result.has_value()) {
        failure_diagnostic =
            assembly.message.empty() ? "prompt-assembly-failed"
                                     : assembly.message;
        return std::nullopt;
    }

    std::string material;
    for (const ak::prompt::AssembledComponent& component :
         assembly.result->Components()) {
        material += component.content;
    }
    if (IsBlank(material)) {
        failure_diagnostic = "assembled prompt material is empty";
        return std::nullopt;
    }
    return ak::model::ModelInput(std::move(material));
}

std::optional<ak::agent::ModelAction>
ModelToRuntimeDecisionComposition::InferAndInterpret(
    const ak::model::ModelInput& input,
    std::string& failure_diagnostic) {
    // Step 2: one Model inference -> one ModelResult.
    const ak::model::ModelResult result = model_binding_.Infer(input);

    // Step 3 (M-001): composition Status() gate. ModelResult::
    // kFailure is classified directly as terminal kFailure BEFORE
    // InterpretModelResult / ModelAction generation / Runtime
    // execution. No ModelAction (no kInvalid conversion) is
    // produced, and no Runtime invocation can occur.
    if (result.Status() == ak::model::ModelStatus::kFailure) {
        failure_diagnostic = result.Diagnostic() +
                             ";model-error-category=" +
                             ErrorCategoryName(result.ErrorCategory());
        return std::nullopt;
    }

    // Step 4: one Agent interpretation (kSuccess / kInvalidResult
    // only). kFailure never reaches InterpretModelResult (M-001).
    return InterpretModelResult(result);
}

}  // namespace ak::model_to_runtime