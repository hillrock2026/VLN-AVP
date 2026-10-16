// ============================================================
// Agent Kernel - AgentContinuationComposition
// ============================================================
// TASK 3.5 - Agent-Owned Observation-Driven Continuation
// Integration.
//
// The minimum Agent-owned, bounded, deterministic integration
// component that starts from the completed observation/context
// state produced by one TASK 3.4 bounded execution cycle and
// provides EXACTLY ONE subsequent decision-generation
// opportunity, reusing the existing Prompt -> Model ->
// ModelResult -> Agent interpretation -> ModelAction ->
// TASK 3.3 Runtime-backed execution path (all REUSED
// UNCHANGED):
//
//   first cycle (ModelToRuntimeDecisionComposition::ExecuteOnce,
//                TASK 3.4, reused unchanged)
//     -> terminal + RuntimeObservation + Context update
//     -> continuation precondition gate (PRE-1..PRE-4)
//     -> BuildContinuationInput (Context-derived material only)
//     -> ONE continuation decision-generation
//        (ExecuteOnce second call, reused unchanged)
//     -> terminal -> STOP
//
// Exactly one bounded continuation:
//   first cycle (1 decision-generation)
//   + ONE continuation opportunity (1 decision-generation)
//   = maximum scope. No while(true), no retry, no recovery,
//   no persistence, no async/background, no third decision.
//
// Boundary (TASK 3.5 Contract sections 8/13/15): the
// composition consumes ONLY the existing Agent-facing surfaces
// (the TASK 3.4 composition, Context, PromptAssemblyRequest).
// It never accesses Runtime internals, Scheduler, Executor,
// CapabilityResolver, EventBus, or the Runtime Public API
// directly, and never creates a Model -> Runtime, Model -> Tool,
// Model -> Context, or Agent -> Runtime-internal path.
//
// NON-responsibilities:
// - NOT a loop, Scheduler, Executor, or second Agent lifecycle.
// - Does NOT redesign Runtime/Model failure semantics; M-001
//   (ModelResult::kFailure -> terminal kFailure through the
//   TASK 3.4 Status() gate) is inherited unchanged.
// ============================================================

#pragma once

#include <agent_kernel/context/context.hpp>
#include <agent_kernel/context/context_identity.hpp>
#include <agent_kernel/model_to_runtime/model_to_runtime_decision_composition.hpp>
#include <agent_kernel/prompt/prompt_request.hpp>
#include <agent_kernel/runtime_backed_agent/runtime_backed_execution_composition.hpp>

namespace ak::agent_continuation {

// ============================================================
// ContinuationOutcome - deterministic outcome of one bounded
// continuation (first cycle + one continuation opportunity).
// ============================================================
struct ContinuationOutcome {
    // TASK 3.4 ExecuteOnce outcome of the first bounded cycle.
    ak::runtime_backed_agent::ExecutionCycleOutcome first_cycle;
    // Outcome of the exactly-one continuation decision-generation.
    // When the continuation does not start, this carries the
    // deterministic "continuation-not-started" marker and
    // continuation_started is false.
    ak::runtime_backed_agent::ExecutionCycleOutcome continuation_cycle;
    // True only when all continuation preconditions were satisfied
    // and the continuation decision-generation was exercised.
    bool continuation_started = false;
};

// ============================================================
// AgentContinuationComposition
// ============================================================
// Agent-owned bounded continuation composition. All references
// are non-owning and MUST outlive the composition.
class AgentContinuationComposition {
public:
    AgentContinuationComposition(
        ak::model_to_runtime::ModelToRuntimeDecisionComposition& model_to_runtime,
        ak::context::Context& context,
        ak::context::ContextObjectId context_object_id);

    AgentContinuationComposition(const AgentContinuationComposition&) = delete;
    AgentContinuationComposition& operator=(
        const AgentContinuationComposition&) = delete;
    AgentContinuationComposition(AgentContinuationComposition&&) = delete;
    AgentContinuationComposition& operator=(AgentContinuationComposition&&) =
        delete;

    ~AgentContinuationComposition() = default;

    // Executes one bounded continuation:
    //   first cycle (TASK 3.4 ExecuteOnce, reused unchanged)
    //   -> continuation precondition gate (PRE-1..PRE-4)
    //   -> ONE next decision-generation (ExecuteOnce second call,
    //      reused unchanged)
    //   -> terminal -> STOP.
    // Decision-generation is bounded to at most two ExecuteOnce
    // calls total. No retry, no recovery, no third decision.
    [[nodiscard]] ContinuationOutcome ExecuteBoundedContinuation(
        const ak::prompt::PromptAssemblyRequest& first_request);

private:
    // Continuation starts ONLY when the first cycle reached
    // terminal kCompleted through the TASK 3.3 Runtime-backed
    // tool path (RuntimeObservation produced) and the completed
    // observation/context state is present in Agent context.
    [[nodiscard]] bool RequireContinuationPreconditions(
        const ak::runtime_backed_agent::ExecutionCycleOutcome& first_cycle)
        const;

    // Builds the second decision-generation input from the
    // completed observation/context state only (Context-derived
    // material through the existing PromptInputBinding
    // semantics). No new variable, no external/synthetic
    // material.
    [[nodiscard]] ak::prompt::PromptAssemblyRequest BuildContinuationInput(
        const ak::prompt::PromptAssemblyRequest& first_request) const;

    ak::model_to_runtime::ModelToRuntimeDecisionComposition& model_to_runtime_;
    ak::context::Context& context_;
    ak::context::ContextObjectId context_object_id_;
};

}  // namespace ak::agent_continuation
