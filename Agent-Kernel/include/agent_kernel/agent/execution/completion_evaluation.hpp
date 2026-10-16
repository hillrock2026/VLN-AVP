// ============================================================
// Agent Kernel - CompletionEvaluation (Agent boundary)
// ============================================================
// Agent-owned intelligent completion evaluation.
//
// P1-IS002 scope (Chapter 8.6 - Completion Evaluation):
// - The Agent MAY evaluate whether an intelligent execution
//   objective has been achieved.
// - This evaluation SHALL remain distinct from Runtime
//   lifecycle completion:
//
//       Runtime completion  !=  Agent intelligent completion
//
// - Runtime SHALL remain authoritative for Runtime object
//   execution lifecycle; Agent SHALL remain authoritative for
//   intelligent objective evaluation.
//
// NON-responsibilities:
// - This representation performs no Runtime observation and
//   references no Runtime type.
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <string_view>
#include <utility>

#include <agent_kernel/agent/execution/execution_objective.hpp>

namespace ak::agent {

// Agent-owned summary of an observed outcome. Phase 1 carries
// the Agent's own representation; it is not Runtime state.
struct ExecutionOutcomeSummary {
    bool success_indicator = false;
    std::string summary;
};

// Result of an Agent-owned intelligent completion evaluation.
class CompletionEvaluation {
public:
    CompletionEvaluation() = default;
    CompletionEvaluation(ObjectiveId objective, bool achieved,
                         std::string rationale)
        : objective_(objective),
          achieved_(achieved),
          rationale_(std::move(rationale)) {}

    [[nodiscard]] ObjectiveId GetObjectiveId() const noexcept { return objective_; }
    [[nodiscard]] bool IsAchieved() const noexcept { return achieved_; }
    [[nodiscard]] const std::string& Rationale() const noexcept { return rationale_; }

    static CompletionEvaluation Achieved(ObjectiveId objective,
                                         std::string rationale) {
        return CompletionEvaluation(objective, true, std::move(rationale));
    }

    static CompletionEvaluation NotAchieved(ObjectiveId objective,
                                            std::string rationale) {
        return CompletionEvaluation(objective, false, std::move(rationale));
    }

private:
    ObjectiveId objective_;
    bool achieved_ = false;
    std::string rationale_;
};

// Evaluates whether the Agent-owned objective was achieved,
// based on the Agent's own outcome representation. The
// evaluation is intelligent and Agent-owned; it does not read
// Runtime lifecycle state.
[[nodiscard]] inline CompletionEvaluation EvaluateCompletion(
    const ExecutionObjective& objective,
    const ExecutionOutcomeSummary& outcome) {
    if (outcome.success_indicator && !outcome.summary.empty()) {
        return CompletionEvaluation::Achieved(
            objective.GetId(), outcome.summary);
    }
    return CompletionEvaluation::NotAchieved(
        objective.GetId(), outcome.summary);
}

}  // namespace ak::agent
