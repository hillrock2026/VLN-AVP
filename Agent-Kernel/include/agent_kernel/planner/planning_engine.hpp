// ============================================================
// Agent Kernel - PlanningEngine (Planner boundary)
// ============================================================
// Planner-owned planning activity contract (P1-IS005 Rev5.1
// Chapter 11; AK0044 Revision A Section 12).
//
// Scope:
// - IPlanningEngine is the Planner-owned engine boundary; the
//   Planner holds a non-owning engine reference injected at
//   construction (engine lifetime >= Planner lifetime).
// - HasOutcome is non-blocking and noexcept; Outcome is invoked
//   at most once per accepted request under the single Planner
//   synchronization boundary.
// - ImmediatePlanningEngine is the deterministic production
//   default: the terminal outcome is available at the first
//   completion attempt.
//
// NON-responsibilities:
// - The engine is not a Runtime/Scheduler/Executor/Workflow/
//   Task adapter; it produces planning outcomes only.
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include <agent_kernel/planner/planner_identity.hpp>
#include <agent_kernel/planner/planner_metadata.hpp>
#include <agent_kernel/planner/planning_request.hpp>

namespace ak::planner {

enum class PlanningOutcomeStatus : std::uint8_t {
    kSuccess = 0,   // planning succeeded; steps and payload produced
    kFailed         // planning failed; reason produced; no artifact
};

struct PlanningOutcome {
    PlanningOutcomeStatus status = PlanningOutcomeStatus::kFailed;
    PlanningMetadata metadata;                  // outcome metadata
    std::vector<std::string> execution_plan_steps;
    std::string artifact_payload;
    std::string message;                        // failure reason or success description
};

class IPlanningEngine {
public:
    virtual ~IPlanningEngine() noexcept = default;

    // True when a terminal outcome for the accepted request is
    // available. SHALL be noexcept and SHALL NOT block.
    [[nodiscard]] virtual bool HasOutcome(
        const PlannerSessionId& session_id,
        const PlanningRequestId& request_id) const noexcept = 0;

    // Produces the terminal outcome. SHALL be invoked at most
    // once per accepted request, only when HasOutcome() is true
    // and the Planner is not Suspended. SHALL be noexcept.
    [[nodiscard]] virtual PlanningOutcome Outcome(
        const PlannerSessionId& session_id,
        const PlanningRequest& request) noexcept = 0;
};

// Production default engine: deterministic, in-memory,
// single-threaded; the terminal outcome is available at the
// first completion attempt (the first completion attempt
// linearizes; kPending is never produced by this engine).
class ImmediatePlanningEngine : public IPlanningEngine {
public:
    ImmediatePlanningEngine() = default;

    [[nodiscard]] bool HasOutcome(const PlannerSessionId&,
                                  const PlanningRequestId&) const noexcept override;

    [[nodiscard]] PlanningOutcome Outcome(const PlannerSessionId&,
                                          const PlanningRequest& request) noexcept override;
};

}  // namespace ak::planner
