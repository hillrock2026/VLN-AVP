// ============================================================
// Agent Kernel - RuntimeBackedExecutionComposition
// ============================================================
// TASK 3.3 - Agent-Owned Runtime-Backed Execution Composition.
//
// The minimum Agent-owned execution composition that consumes
// the CLOSED TASK 3.2 Runtime integration contract and performs
// one bounded, deterministic, synchronous execution step
// through the sanctioned Agent -> Runtime boundary:
//
//   ModelAction -> Agent-owned execution composition
//       -> RuntimeInvocationRequest -> RuntimeInteractionPort
//       -> RuntimePublicApiAdapter -> Runtime Public API
//       -> Runtime -> Real CapabilityInvoker -> ExecutionResult
//       -> RuntimeObservation -> existing Context API
//       -> terminal state
//
// Ownership (TASK 3.3 Contract 6.1): Agent owns execution
// coordination, decision interpretation, bounded execution
// flow, observation interpretation, Context update
// coordination, and the terminal decision.
//
// Boundary (TASK 3.3 Contract 7): the composition sees ONLY
// the Agent-owned RuntimeInteractionPort; it never accesses
// Runtime internals, Scheduler, Executor, CapabilityResolver,
// EventBus, or Runtime internal result types. RuntimePublicApiAdapter
// remains the sole Agent -> Runtime production bridge.
//
// Minimum execution shape (TASK 3.3 Contract 19): one Agent
// decision -> zero or one Runtime invocation -> one resulting
// observation -> one Context update -> terminal state. The
// Runtime state machine is one-shot (Created -> Running ->
// Stopped; Runtime::Run requires kCreated), and the immutable
// boundary allows only the adapter translation unit to include
// the Runtime Public API; therefore each Execute performs at
// most one Runtime invocation through the injected port.
//
// NON-responsibilities:
// - This is NOT a Runtime loop, Scheduler, Executor, or second
//   Agent lifecycle.
// - No retry, recovery, cancellation, async, background, or
//   persistent result behavior exists.
// - No new Observation framework is introduced: RuntimeObservation
//   remains the Agent-facing observation value.
// ============================================================

#pragma once

#include <cstdint>
#include <string>

#include <agent_kernel/agent/runtime/runtime_interaction_port.hpp>
#include <agent_kernel/context/context.hpp>
#include <agent_kernel/context/context_identity.hpp>
#include <agent_kernel/fwa/model_action.hpp>

namespace ak::runtime_backed_agent {

// ============================================================
// ExecutionTermination - terminal classification of one
// execution step.
// ============================================================
enum class ExecutionTermination : std::uint8_t {
    kCompleted = 0,  // kComplete decision or successful invocation
    kInvalid,        // kInvalid decision -> deterministic invalid
    kFailure         // deterministic execution failure
};

// ============================================================
// ExecutionCycleOutcome - deterministic outcome of one step.
// ============================================================
struct ExecutionCycleOutcome {
    bool completed = false;
    ExecutionTermination termination = ExecutionTermination::kFailure;
    std::string summary;      // deterministic summary
    std::string diagnostics;  // deterministic evidence
};

// ============================================================
// RuntimeBackedExecutionComposition
// ============================================================
// Agent-owned bounded execution composition. Port and Context
// are injected (non-owning references; both MUST outlive the
// composition). Runtime + adapter wiring is the integration
// bootstrap (TASK 3.1 17): the composition consumes the port.
class RuntimeBackedExecutionComposition {
public:
    RuntimeBackedExecutionComposition(
        ak::agent::RuntimeInteractionPort& port,
        ak::context::Context& context,
        ak::context::ContextObjectId context_object_id);

    RuntimeBackedExecutionComposition(
        const RuntimeBackedExecutionComposition&) = delete;
    RuntimeBackedExecutionComposition& operator=(
        const RuntimeBackedExecutionComposition&) = delete;

    // Executes one bounded deterministic Agent decision:
    //   kComplete  -> terminal kCompleted, NO Runtime invocation;
    //   kInvalid   -> terminal kInvalid, NO Runtime invocation;
    //   kToolInvoke-> one Runtime invocation through the port,
    //                 one RuntimeObservation, one Context update,
    //                 terminal kCompleted (success) or kFailure.
    [[nodiscard]] ExecutionCycleOutcome Execute(
        const ak::agent::ModelAction& decision);

private:
    // One kToolInvoke step: build RuntimeInvocationRequest,
    // Submit, Observe, apply observation to Context.
    [[nodiscard]] ExecutionCycleOutcome InvokeTool(
        const ak::agent::ModelAction& action);

    // Applies a RuntimeObservation to the target Context Object
    // through ContextAgentContract::Update (Begin/Apply/Complete).
    [[nodiscard]] bool ApplyObservation(
        const ak::agent::RuntimeObservation& observation);

    ak::agent::RuntimeInteractionPort& port_;
    ak::context::Context& context_;
    ak::context::ContextObjectId context_object_id_;
    std::uint64_t invocation_counter_ = 0;
};

}  // namespace ak::runtime_backed_agent
