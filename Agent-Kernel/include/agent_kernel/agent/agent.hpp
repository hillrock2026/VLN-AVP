// ============================================================
// Agent Kernel - Agent (Agent boundary)
// ============================================================
// The Agent object: the Phase 1 Agent implementation boundary.
//
// P1-IS002 scope (Chapter 16 - Agent Object Model):
// The Agent object contains, directly or indirectly:
//   - Agent identity;
//   - Agent lifecycle state (the single architectural state
//     model);
//   - Agent state;
//   - Agent-owned coordination references;
//   - Agent-owned execution state (objectives, composition,
//     supervision, completion evaluation);
//   - Agent-specific extension attachment state;
//   - Agent-owned Runtime interaction port/contract reference.
//
// NON-responsibilities:
// - The Agent object is NOT a container for authoritative state
//   belonging to Memory, Context, Planner, Tool, or Runtime.
// - It does not access Runtime internals and holds no Runtime
//   type.
// - It is not a universal coordinator or lifecycle manager.
// ============================================================

#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <agent_kernel/agent/agent_identity.hpp>
#include <agent_kernel/agent/agent_state.hpp>
#include <agent_kernel/agent/coordination/agent_coordination_service.hpp>
#include <agent_kernel/agent/execution/completion_evaluation.hpp>
#include <agent_kernel/agent/execution/execution_composition.hpp>
#include <agent_kernel/agent/execution/execution_objective.hpp>
#include <agent_kernel/agent/execution/execution_supervision.hpp>
#include <agent_kernel/agent/extension/agent_extension_boundary.hpp>
#include <agent_kernel/agent/runtime/runtime_interaction_port.hpp>
#include <agent_kernel/foundation/kernel_diagnostics.hpp>
#include <agent_kernel/foundation/kernel_lifecycle.hpp>
#include <agent_kernel/foundation/kernel_metadata.hpp>
#include <agent_kernel/foundation/kernel_registry.hpp>

namespace ak::agent {

class Agent {
public:
    explicit Agent(AgentIdentity identity);

    // -- Identity --
    [[nodiscard]] AgentIdentity GetIdentity() const noexcept { return identity_; }

    // -- Metadata --
    void SetMetadata(ak::KernelMetadata metadata) { metadata_ = std::move(metadata); }
    [[nodiscard]] const ak::KernelMetadata& GetMetadata() const noexcept {
        return metadata_;
    }

    // --------------------------------------------------------
    // Lifecycle / state (single architectural model)
    // --------------------------------------------------------
    [[nodiscard]] AgentState GetState() const noexcept { return state_; }

    [[nodiscard]] std::string_view GetStateName() const noexcept;

    // Initialization: Uninitialized -> Ready.
    [[nodiscard]] ak::TransitionResult Initialize();

    // Ready -> Coordinating. Requires all four peer subsystem
    // contracts to be bound.
    [[nodiscard]] ak::TransitionResult BeginCoordination();

    // Coordinating -> Supervising.
    [[nodiscard]] ak::TransitionResult EnterSupervising();

    // Supervising -> Coordinating (adaptation).
    [[nodiscard]] ak::TransitionResult ReturnToCoordinating();

    // Supervising -> Suspended. Suspends Agent intelligent
    // coordination only; Runtime execution remains Runtime-owned.
    [[nodiscard]] ak::TransitionResult Suspend();

    // Suspended -> Ready.
    [[nodiscard]] ak::TransitionResult Resume();

    // Ready -> Terminated. Ends Agent intelligent coordination
    // without altering Runtime lifecycle.
    [[nodiscard]] ak::TransitionResult Terminate();

    // --------------------------------------------------------
    // Execution objectives (Agent-owned)
    // --------------------------------------------------------
    // Accepts a new execution objective. Objectives are accepted
    // while Ready, Coordinating, or Supervising; they are
    // rejected while Uninitialized, Suspended, or Terminated.
    [[nodiscard]] bool AcceptObjective(const ExecutionObjective& objective);

    [[nodiscard]] const ExecutionObjective* FindObjective(ObjectiveId id) const noexcept;

    [[nodiscard]] std::vector<ObjectiveId> EnumerateObjectives() const;

    // --------------------------------------------------------
    // Subsystem coordination (Agent-owned, sole path)
    // --------------------------------------------------------
    [[nodiscard]] AgentCoordinationService& Coordination() noexcept {
        return coordination_;
    }

    [[nodiscard]] const AgentCoordinationService& Coordination() const noexcept {
        return coordination_;
    }

    [[nodiscard]] bool HasAllSubsystemContracts() const noexcept {
        return coordination_.AllBound();
    }

    // --------------------------------------------------------
    // Execution composition (Agent-owned representation)
    // --------------------------------------------------------
    [[nodiscard]] ExecutionComposition& Composition() noexcept { return composition_; }

    [[nodiscard]] const ExecutionComposition& Composition() const noexcept {
        return composition_;
    }

    // --------------------------------------------------------
    // Execution supervision (Agent-owned representation)
    // --------------------------------------------------------
    [[nodiscard]] ExecutionSupervision& Supervision() noexcept { return supervision_; }

    [[nodiscard]] const ExecutionSupervision& Supervision() const noexcept {
        return supervision_;
    }

    // Begins Agent supervision of an accepted objective. Only
    // valid while Supervising.
    [[nodiscard]] bool BeginSupervision(ObjectiveId objective);

    // --------------------------------------------------------
    // Completion evaluation (Agent-owned, distinct from Runtime)
    // --------------------------------------------------------
    [[nodiscard]] CompletionEvaluation EvaluateObjective(
        ObjectiveId objective, const ExecutionOutcomeSummary& outcome) const;

    // --------------------------------------------------------
    // Agent-specific extension boundary
    // --------------------------------------------------------
    [[nodiscard]] AgentExtensionBoundary& Extensions() noexcept { return extensions_; }

    [[nodiscard]] const AgentExtensionBoundary& Extensions() const noexcept {
        return extensions_;
    }

    // --------------------------------------------------------
    // Runtime interaction port (Phase 1 contract only)
    // --------------------------------------------------------
    [[nodiscard]] const RuntimeInteractionPort& RuntimePort() const noexcept {
        return runtime_port_;
    }

    // --------------------------------------------------------
    // Diagnostics (owner-scoped)
    // --------------------------------------------------------
    [[nodiscard]] ak::DiagnosticSink& Diagnostics() noexcept { return diagnostics_; }

    [[nodiscard]] const ak::DiagnosticSink& Diagnostics() const noexcept {
        return diagnostics_;
    }

private:
    // Requests a transition. The transition is only legal when the
    // Agent is currently in `required_from`; rejected transitions
    // leave the state unchanged and record an owner-scoped
    // diagnostic.
    [[nodiscard]] ak::TransitionResult RequestTransition(
        AgentState required_from, AgentState target);

    AgentIdentity identity_;
    ak::KernelMetadata metadata_;
    AgentState state_ = AgentState::kUninitialized;
    ak::LifecycleTransitionValidator validator_;
    AgentCoordinationService coordination_;
    ak::OwnerScopedRegistry<ObjectiveId, ExecutionObjective> objectives_;
    ExecutionComposition composition_;
    ExecutionSupervision supervision_;
    AgentExtensionBoundary extensions_;
    RuntimeInteractionPort runtime_port_;
    ak::DiagnosticSink diagnostics_;
};

}  // namespace ak::agent
