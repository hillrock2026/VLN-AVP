// ============================================================
// Agent Kernel - PlannerSession (Planner boundary)
// ============================================================
// Planner-owned session and exchange processing state
// (P1-IS005 Rev5.1 Chapter 7.3; AK0044 Revision A Section 8).
//
// Scope:
// - One primary Planner Session SHALL be created by the
//   Planner during Activate and retired when the Planner
//   reaches Terminated.
// - PlannerRequestState is the Planner-owned processing state
//   of one accepted request; it is not externally mutable.
// - Sessions never become Agent/Kernel/Workflow/Task/Runtime
//   objects; session lifetime never extends the Planner
//   lifetime.
//
// NON-responsibilities:
// - Sessions are not Runtime sessions, not lifecycle
//   authorities, and not coordination services.
// ============================================================

#pragma once

#include <cstddef>
#include <cstdint>
#include <unordered_set>
#include <vector>

#include <agent_kernel/planner/planner_identity.hpp>
#include <agent_kernel/planner/planning_request.hpp>

namespace ak::planner {

enum class PlannerExchangeStatus : std::uint8_t {
    kOpen = 0,    // accepted; terminal result not yet published
    kRetired      // terminal result published; exchange retired
};

// Planner-owned processing state of one accepted request
// (AK0044 Revision A Section 12.2). Not externally mutable.
class PlannerRequestState {
public:
    PlannerRequestState(PlanningRequestId request_id, PlannerSessionId session_id,
                        PlanningRequest request_snapshot);

    [[nodiscard]] PlanningRequestId GetRequestId() const noexcept;
    [[nodiscard]] PlannerSessionId GetSessionId() const noexcept;
    [[nodiscard]] PlannerExchangeStatus GetStatus() const noexcept;
    [[nodiscard]] const PlanningRequest& GetRequest() const noexcept;
    [[nodiscard]] bool HasTerminalResult() const noexcept;
    [[nodiscard]] PlanningResultId GetResultId() const noexcept;

private:
    friend class PlanningService;
    PlanningRequestId request_id_;
    PlannerSessionId session_id_;
    PlanningRequest request_;                  // Planner-owned value copy
    PlannerExchangeStatus status_ = PlannerExchangeStatus::kOpen;
    bool has_terminal_result_ = false;
    PlanningResultId result_id_;               // assigned at linearization
};

class PlannerSession {
public:
    explicit PlannerSession(PlannerSessionId id);

    [[nodiscard]] PlannerSessionId GetId() const noexcept;
    [[nodiscard]] std::size_t OpenExchangeCount() const noexcept;
    [[nodiscard]] std::size_t ExchangeCount() const noexcept;
    [[nodiscard]] std::vector<PlannerRequestState> SnapshotExchanges() const;

private:
    friend class PlanningService;
    PlannerSessionId id_;
    std::vector<PlannerRequestState> exchanges_;       // insertion order = acceptance order
    std::unordered_set<PlanningRequestId> retired_requests_;
};

}  // namespace ak::planner
