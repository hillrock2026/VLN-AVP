// ============================================================
// Agent Kernel - ModelToRuntimeDecisionComposition
// ============================================================
// TASK 3.4 - Agent-owned Model-to-Runtime decision integration.
//
// The smallest Agent-owned, bounded, deterministic integration
// path that consumes the existing Prompt -> Model -> ModelResult
// capability, interprets the ModelResult into the existing
// Agent-owned ModelAction, and hands that decision to the CLOSED
// TASK 3.3 RuntimeBackedExecutionComposition (REUSED UNCHANGED):
//
//   PromptAssemblyRequest
//     -> AgentPromptBinding::Assemble (existing)
//     -> ModelInput
//     -> AgentModelBinding::Infer (existing)
//     -> ModelResult
//     -> Status() gate (M-001: kFailure -> terminal kFailure)
//     -> InterpretModelResult (kSuccess / kInvalidResult only)
//     -> ModelAction
//     -> RuntimeBackedExecutionComposition::Execute (TASK 3.3)
//     -> Runtime -> RuntimeObservation -> Context -> terminal
//
// One bounded cycle only (Contract section 7): one Prompt
// assembly, one Model inference, one ModelResult, one
// interpretation, zero/one ModelAction, zero/one Runtime
// invocation, one observation, one Context update, one terminal
// outcome. No retry, no async, no persistence, no second cycle.
//
// Boundary (Contract section 8): the composition consumes ONLY
// the existing Agent-facing bindings and the TASK 3.3
// composition. It never accesses Runtime internals, Scheduler,
// Executor, CapabilityResolver, EventBus, or the Runtime Public
// API directly, and never creates a Model -> Runtime,
// Model -> Tool, Model -> Context, or Model -> Agent lifecycle
// path.
//
// NON-responsibilities:
// - The composition is NOT a Runtime loop, Scheduler, Executor,
//   or second Agent lifecycle.
// - The composition does NOT redesign Runtime failure semantics;
//   Runtime/Context failures consume the existing TASK 3.3
//   semantics unchanged.
// ============================================================

#pragma once

#include <optional>
#include <string>

#include <agent_kernel/agent_model/agent_model_binding.hpp>
#include <agent_kernel/agent_prompt/agent_prompt_binding.hpp>
#include <agent_kernel/fwa/model_action.hpp>
#include <agent_kernel/model/model_input.hpp>
#include <agent_kernel/prompt/prompt_request.hpp>
#include <agent_kernel/runtime_backed_agent/runtime_backed_execution_composition.hpp>

namespace ak::model_to_runtime {

// Agent-owned integration composition joining existing decision
// generation (Prompt/Model) to the CLOSED TASK 3.3 execution
// composition. All three references are non-owning and MUST
// outlive the composition.
class ModelToRuntimeDecisionComposition {
public:
    ModelToRuntimeDecisionComposition(
        ak::agent::AgentPromptBinding& prompt_binding,
        ak::agent::AgentModelBinding& model_binding,
        ak::runtime_backed_agent::RuntimeBackedExecutionComposition&
            runtime_composition);

    ModelToRuntimeDecisionComposition(
        const ModelToRuntimeDecisionComposition&) = delete;
    ModelToRuntimeDecisionComposition& operator=(
        const ModelToRuntimeDecisionComposition&) = delete;
    ModelToRuntimeDecisionComposition(ModelToRuntimeDecisionComposition&&) =
        delete;
    ModelToRuntimeDecisionComposition& operator=(
        ModelToRuntimeDecisionComposition&&) = delete;

    ~ModelToRuntimeDecisionComposition() = default;

    // Executes exactly one bounded deterministic cycle
    // (Contract section 7):
    //   one Prompt assembly -> one ModelInput -> one inference
    //   -> one ModelResult -> one Status() gate (M-001)
    //   -> one interpretation -> zero/one ModelAction
    //   -> zero/one Runtime invocation (kToolInvoke only)
    //   -> one observation -> one Context update -> terminal.
    [[nodiscard]] ak::runtime_backed_agent::ExecutionCycleOutcome ExecuteOnce(
        const ak::prompt::PromptAssemblyRequest& request);

private:
    // Step 1: one Prompt assembly -> one ModelInput. Returns
    // nullopt (and records deterministic failure evidence) when
    // assembly fails or produces empty/whitespace-only material
    // that ModelInput deterministically rejects.
    [[nodiscard]] std::optional<ak::model::ModelInput> AssembleModelInput(
        const ak::prompt::PromptAssemblyRequest& request,
        std::string& failure_diagnostic);

    // Steps 2-4: one inference, one Status() gate (M-001), one
    // interpretation. ModelResult::kFailure is detected BEFORE
    // InterpretModelResult / ModelAction generation / Runtime
    // execution: returns nullopt and records the deterministic
    // failure evidence so ExecuteOnce terminates as kFailure
    // with NO ModelAction and NO Runtime invocation.
    [[nodiscard]] std::optional<ak::agent::ModelAction> InferAndInterpret(
        const ak::model::ModelInput& input,
        std::string& failure_diagnostic);

    ak::agent::AgentPromptBinding& prompt_binding_;
    ak::agent::AgentModelBinding& model_binding_;
    ak::runtime_backed_agent::RuntimeBackedExecutionComposition&
        runtime_composition_;
};

}  // namespace ak::model_to_runtime