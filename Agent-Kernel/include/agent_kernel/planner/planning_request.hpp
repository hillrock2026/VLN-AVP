// ============================================================
// Agent Kernel - PlanningRequest (Planner boundary)
// ============================================================
// Agent-owned immutable planning request value (P1-IS005
// Rev5.1 Chapter 9; AK0044 Revision A Section 12.1).
//
// Scope:
// - The Agent creates the request and assigns request_id at
//   construction; the request remains Agent-owned.
// - Submission is a value copy into Planner-owned processing
//   state; Planner never borrows or mutates the Agent value.
// - request_id must be unique per session (active and retired);
//   reuse after retirement is refused to preserve one-to-one
//   request -> result correlation.
//
// NON-responsibilities:
// - PlanningRequest is not a Runtime request and references no
//   Runtime type.
// ============================================================

#pragma once

#include <string>
#include <vector>

#include <agent_kernel/planner/planner_identity.hpp>
#include <agent_kernel/planner/planner_metadata.hpp>

namespace ak::planner {

struct PlanningRequest {
    PlanningRequestId request_id;      // Agent-assigned; unique per session
    PlannerSessionId session_id;       // SHALL equal the primary session id
    PlanningMetadata metadata;         // immutable request metadata
    std::string goal;                  // planning objective (non-empty)
    std::vector<std::string> constraints;  // optional constraints

    [[nodiscard]] bool operator==(const PlanningRequest&) const noexcept = default;

    // Valid only when request_id and session_id are valid and
    // goal is non-empty.
    [[nodiscard]] bool IsValid() const noexcept {
        return request_id.IsValid() && session_id.IsValid() && !goal.empty();
    }
};

}  // namespace ak::planner
