// ============================================================
// Agent Kernel - Agent (Agent boundary)
// ============================================================
// Implementation of the Phase 1 Agent object.
// ============================================================

#include <agent_kernel/agent/agent.hpp>

#include <utility>

namespace ak::agent {

Agent::Agent(AgentIdentity identity)
    : identity_(identity), validator_(&AgentStateTransitionRule) {}

std::string_view Agent::GetStateName() const noexcept {
    return AgentStateName(state_);
}

ak::TransitionResult Agent::RequestTransition(AgentState required_from,
                                              AgentState target) {
    // The Agent initiates its own transitions; the Foundation
    // validator only validates the normative transition rule.
    // Each lifecycle operation also declares the architectural
    // state it may start from, so an operation cannot be used to
    // shortcut into a state it does not own.
    if (state_ != required_from) {
        constexpr const char* message =
            "transition is not permitted from the current Agent state";
        diagnostics_.Add(ak::DiagnosticSeverity::kWarning, 1, message);
        return {ak::TransitionStatus::kRejected, message};
    }
    ak::TransitionResult result = validator_.Validate(
        ToLifecycleState(state_), ToLifecycleState(target));
    if (result.Accepted()) {
        state_ = target;
    } else {
        diagnostics_.Add(ak::DiagnosticSeverity::kWarning, 1,
                         result.message);
    }
    return result;
}

ak::TransitionResult Agent::Initialize() {
    return RequestTransition(AgentState::kUninitialized, AgentState::kReady);
}

ak::TransitionResult Agent::BeginCoordination() {
    ak::TransitionResult result =
        RequestTransition(AgentState::kReady, AgentState::kCoordinating);
    if (result.Rejected()) {
        return result;
    }
    if (!coordination_.AllBound()) {
        diagnostics_.Add(ak::DiagnosticSeverity::kError, 2,
                         "cannot coordinate without all subsystem contracts bound");
        state_ = AgentState::kReady;
        return {ak::TransitionStatus::kRejected,
                "cannot coordinate without all subsystem contracts bound"};
    }

    // Agent invokes the peer subsystem contracts (Phase 1
    // acknowledgments only; no subsystem behavior is
    // implemented by the Agent).
    const auto memory = coordination_.CoordinateMemory();
    const auto context = coordination_.CoordinateContext();
    const auto planner = coordination_.CoordinatePlanner();
    const auto tool = coordination_.CoordinateTool();

    if (!memory.accepted || !context.accepted ||
        !planner.accepted || !tool.accepted) {
        diagnostics_.Add(ak::DiagnosticSeverity::kError, 3,
                         "subsystem contract acknowledgment failed");
        state_ = AgentState::kReady;
        return {ak::TransitionStatus::kRejected,
                "subsystem contract acknowledgment failed"};
    }
    return result;
}

ak::TransitionResult Agent::EnterSupervising() {
    return RequestTransition(AgentState::kCoordinating,
                             AgentState::kSupervising);
}

ak::TransitionResult Agent::ReturnToCoordinating() {
    return RequestTransition(AgentState::kSupervising,
                             AgentState::kCoordinating);
}

ak::TransitionResult Agent::Suspend() {
    return RequestTransition(AgentState::kSupervising,
                             AgentState::kSuspended);
}

ak::TransitionResult Agent::Resume() {
    return RequestTransition(AgentState::kSuspended,
                             AgentState::kReady);
}

ak::TransitionResult Agent::Terminate() {
    return RequestTransition(AgentState::kReady,
                             AgentState::kTerminated);
}

bool Agent::AcceptObjective(const ExecutionObjective& objective) {
    switch (state_) {
        case AgentState::kReady:
        case AgentState::kCoordinating:
        case AgentState::kSupervising:
            break;
        default:
            diagnostics_.Add(ak::DiagnosticSeverity::kError, 4,
                             "objective rejected: Agent is not accepting objectives");
            return false;
    }

    auto copy = std::make_unique<ExecutionObjective>(objective);
    copy->Accept();
    objectives_.Register(objective.GetId(), std::move(copy));
    return true;
}

const ExecutionObjective* Agent::FindObjective(ObjectiveId id) const noexcept {
    return objectives_.Find(id);
}

std::vector<ObjectiveId> Agent::EnumerateObjectives() const {
    return objectives_.Enumerate();
}

bool Agent::BeginSupervision(ObjectiveId objective) {
    if (state_ != AgentState::kSupervising) {
        diagnostics_.Add(ak::DiagnosticSeverity::kError, 5,
                         "supervision requires the Supervising state");
        return false;
    }
    if (FindObjective(objective) == nullptr) {
        diagnostics_.Add(ak::DiagnosticSeverity::kError, 6,
                         "supervision objective is not accepted");
        return false;
    }
    supervision_.Begin(objective);
    return true;
}

CompletionEvaluation Agent::EvaluateObjective(
    ObjectiveId objective, const ExecutionOutcomeSummary& outcome) const {
    const ExecutionObjective* found = FindObjective(objective);
    if (found == nullptr) {
        return CompletionEvaluation::NotAchieved(
            objective, "objective not found");
    }
    return EvaluateCompletion(*found, outcome);
}

}  // namespace ak::agent
