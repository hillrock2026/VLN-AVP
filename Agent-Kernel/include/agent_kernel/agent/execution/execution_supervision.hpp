// ============================================================
// Agent Kernel - ExecutionSupervision (Agent boundary)
// ============================================================
// Agent-owned supervision representation.
//
// P1-IS002 scope (Chapter 8.4 - Execution Supervision):
// - The implementation SHALL support Agent-owned supervision
//   of Runtime execution as an intelligent responsibility.
// - Supervision MAY include status observation, progress
//   interpretation, result interpretation, continuation
//   decisions, adaptation, and additional planning.
//
// NON-responsibilities (P1-IS002 Chapter 15.6):
// - Phase 1 SHALL NOT implement Runtime status observation.
//   This representation carries Agent-owned interpretations
//   only; it performs no Runtime observation and exposes no
//   Runtime type.
// - Supervision SHALL NOT become Runtime execution.
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <string_view>
#include <utility>

#include <agent_kernel/agent/execution/execution_objective.hpp>

namespace ak::agent {

// Internal phase of Agent-owned supervision. This is an
// internal representation detail, not an architectural state.
enum class SupervisionPhase : std::uint8_t {
    kNotSupervising = 0,
    kObserving,
    kEvaluating,
    kContinuationDecided
};

class ExecutionSupervision {
public:
    ExecutionSupervision() = default;

    // Begins supervision of the given Agent-owned objective.
    void Begin(ObjectiveId objective) noexcept {
        active_ = true;
        objective_ = objective;
        phase_ = SupervisionPhase::kObserving;
        continue_execution_ = true;
        interpretation_.clear();
    }

    void SetPhase(SupervisionPhase phase) noexcept { phase_ = phase; }

    // Records the Agent's own interpretation of observed
    // progress. Phase 1: representation only, no Runtime access.
    void RecordInterpretation(std::string interpretation) {
        interpretation_ = std::move(interpretation);
    }

    // Records the Agent's intelligent continuation decision.
    void DecideContinuation(bool continue_execution) noexcept {
        phase_ = SupervisionPhase::kContinuationDecided;
        continue_execution_ = continue_execution;
    }

    // -- Query --
    [[nodiscard]] bool IsActive() const noexcept { return active_; }

    [[nodiscard]] ObjectiveId GetObjectiveId() const noexcept { return objective_; }

    [[nodiscard]] SupervisionPhase GetPhase() const noexcept { return phase_; }

    [[nodiscard]] const std::string& GetInterpretation() const noexcept {
        return interpretation_;
    }

    [[nodiscard]] bool ContinueExecution() const noexcept {
        return continue_execution_;
    }

private:
    bool active_ = false;
    ObjectiveId objective_;
    SupervisionPhase phase_ = SupervisionPhase::kNotSupervising;
    std::string interpretation_;
    bool continue_execution_ = true;
};

}  // namespace ak::agent
