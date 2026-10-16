// ============================================================
// Agent Kernel - PlannerSession (Planner boundary)
// ============================================================
// Implementation of the Planner-owned session and exchange
// processing state.
// ============================================================

#include <agent_kernel/planner/planner_session.hpp>

#include <utility>

namespace ak::planner {

PlannerRequestState::PlannerRequestState(PlanningRequestId request_id,
                                         PlannerSessionId session_id,
                                         PlanningRequest request_snapshot)
    : request_id_(request_id),
      session_id_(session_id),
      request_(std::move(request_snapshot)) {}

PlanningRequestId PlannerRequestState::GetRequestId() const noexcept {
    return request_id_;
}

PlannerSessionId PlannerRequestState::GetSessionId() const noexcept {
    return session_id_;
}

PlannerExchangeStatus PlannerRequestState::GetStatus() const noexcept {
    return status_;
}

const PlanningRequest& PlannerRequestState::GetRequest() const noexcept {
    return request_;
}

bool PlannerRequestState::HasTerminalResult() const noexcept {
    return has_terminal_result_;
}

PlanningResultId PlannerRequestState::GetResultId() const noexcept {
    return result_id_;
}

PlannerSession::PlannerSession(PlannerSessionId id) : id_(id) {}

PlannerSessionId PlannerSession::GetId() const noexcept {
    return id_;
}

std::size_t PlannerSession::OpenExchangeCount() const noexcept {
    std::size_t count = 0;
    for (const auto& exchange : exchanges_) {
        if (exchange.GetStatus() == PlannerExchangeStatus::kOpen) {
            ++count;
        }
    }
    return count;
}

std::size_t PlannerSession::ExchangeCount() const noexcept {
    return exchanges_.size();
}

std::vector<PlannerRequestState> PlannerSession::SnapshotExchanges() const {
    return exchanges_;
}

}  // namespace ak::planner
