// ============================================================
// Agent Kernel - PlannerServices (Planner boundary)
// ============================================================
// Implementation of the three Planner Services.
//
// Every service operation SHALL execute entirely under the
// single Planner-owned synchronization boundary (one std::mutex
// owned by the Planner root; P1-IS005 Rev5.1 Chapter 12.2), so
// operations linearize in a total order.
//
// Completion protocol (Chapter 12.2):
//   1. request_id unknown in the session  -> kRejectedInvalid
//   2. exchange retired                   -> kRejectedDuplicate
//   3. lifecycle == Suspended             -> kSuspended
//   4. engine.HasOutcome() == false       -> kPending
//   5. engine.HasOutcome() == true        -> LINEARIZE
// ============================================================

#include <agent_kernel/planner/planner_services.hpp>

#include <cstddef>
#include <memory>
#include <mutex>
#include <utility>
#include <vector>

#include <agent_kernel/planner/planner.hpp>
#include <agent_kernel/planner/planner_identity.hpp>
#include <agent_kernel/planner/planner_session.hpp>
#include <agent_kernel/planner/planning_artifact.hpp>
#include <agent_kernel/planner/planning_engine.hpp>
#include <agent_kernel/planner/planning_request.hpp>

namespace ak::planner {

PlanningService::PlanningService(Planner& owner) noexcept : owner_(&owner) {}

PlanningAcceptance PlanningService::Submit(const PlanningRequest& request) {
    std::lock_guard<std::mutex> lock(owner_->mutex_);
    Planner& planner = *owner_;

    // Acceptance precondition 1: lifecycle is Ready or Planning.
    if (planner.lifecycle_ != PlannerLifecycleState::kReady &&
        planner.lifecycle_ != PlannerLifecycleState::kPlanning) {
        return {PlanningAcceptanceStatus::kUnavailable,
                "planner cannot accept requests in the current lifecycle state",
                request.request_id, request.session_id};
    }

    // Precondition 2: request validity (valid ids, non-empty goal).
    if (!request.IsValid()) {
        return {PlanningAcceptanceStatus::kRefused, "invalid request",
                request.request_id, request.session_id};
    }

    // Precondition 3: session association (primary session only).
    if (planner.session_ == nullptr ||
        request.session_id != planner.session_->GetId()) {
        return {PlanningAcceptanceStatus::kRefused,
                "session id does not match the primary session",
                request.request_id, request.session_id};
    }

    // Precondition 4: request id is not already active and not
    // already retired in the session.
    PlannerSession& session = *planner.session_;
    if (session.retired_requests_.find(request.request_id) !=
        session.retired_requests_.end()) {
        bool active = false;
        for (const auto& exchange : session.exchanges_) {
            if (exchange.GetRequestId() == request.request_id &&
                exchange.GetStatus() == PlannerExchangeStatus::kOpen) {
                active = true;
                break;
            }
        }
        return {PlanningAcceptanceStatus::kRefused,
                active ? "request id already active" : "request id already retired",
                request.request_id, request.session_id};
    }

    // Precondition 5: value copy into Planner-owned processing
    // state. On allocation failure no exchange is opened and no
    // partial state remains.
    try {
        session.exchanges_.emplace_back(request.request_id, request.session_id,
                                        request);
        session.retired_requests_.insert(request.request_id);
    } catch (...) {
        if (!session.exchanges_.empty() &&
            session.exchanges_.back().GetRequestId() == request.request_id) {
            session.exchanges_.pop_back();
        }
        return {PlanningAcceptanceStatus::kRefused,
                "request rejected; internal allocation failure",
                request.request_id, request.session_id};
    }

    // Ready -> Planning automatic transition, committed
    // atomically with the acceptance (Chapter 10.4).
    if (planner.lifecycle_ == PlannerLifecycleState::kReady) {
        planner.lifecycle_ = PlannerLifecycleState::kPlanning;
    }

    return {PlanningAcceptanceStatus::kAccepted, "request accepted",
            request.request_id, request.session_id};
}

PlanningCompletionResult PlanningService::CompletePlanningExchange(
    const PlanningRequestId& request_id) {
    std::lock_guard<std::mutex> lock(owner_->mutex_);
    Planner& planner = *owner_;

    // Defensive: Planner already Terminated. The production host
    // refuses earlier through the binding gate (Chapter 15.3).
    if (planner.lifecycle_ == PlannerLifecycleState::kTerminated) {
        return {PlanningCompletionStatus::kRejectedTerminated,
                "planner terminated", PlanningResult{}};
    }
    if (planner.session_ == nullptr) {
        return {PlanningCompletionStatus::kRejectedInvalid,
                "no active planner session", PlanningResult{}};
    }
    PlannerSession& session = *planner.session_;

    // Step 1: request id unknown in the session -> kRejectedInvalid.
    auto exchange = session.exchanges_.end();
    for (auto it = session.exchanges_.begin(); it != session.exchanges_.end(); ++it) {
        if (it->GetRequestId() == request_id) {
            exchange = it;
            break;
        }
    }
    if (exchange == session.exchanges_.end()) {
        return {PlanningCompletionStatus::kRejectedInvalid,
                "unknown request id", PlanningResult{}};
    }

    // Step 2: exchange retired -> kRejectedDuplicate (no second result).
    if (exchange->GetStatus() == PlannerExchangeStatus::kRetired) {
        return {PlanningCompletionStatus::kRejectedDuplicate,
                "exchange already retired", PlanningResult{}};
    }

    // Step 3: lifecycle == Suspended -> kSuspended (exchange preserved).
    if (planner.lifecycle_ == PlannerLifecycleState::kSuspended) {
        return {PlanningCompletionStatus::kSuspended,
                "planner suspended; exchange preserved", PlanningResult{}};
    }

    // Step 4: outcome not yet available -> kPending (exchange preserved).
    if (!planner.engine_->HasOutcome(session.GetId(), request_id)) {
        return {PlanningCompletionStatus::kPending,
                "planning outcome not yet available", PlanningResult{}};
    }

    // Step 5: LINEARIZE. Exactly one completion attempt produces
    // the terminal result; every later attempt is kRejectedDuplicate.
    PlanningOutcome outcome;
    bool engine_succeeded = false;
    try {
        outcome = planner.engine_->Outcome(session.GetId(), exchange->GetRequest());
        engine_succeeded = true;
    } catch (...) {
        // Throwing engine -> deterministic terminal kFailed result.
        engine_succeeded = false;
    }

    PlanningResult result;
    result.result_id = planner.NextResultId();
    result.request_id = request_id;
    result.session_id = session.GetId();
    result.status = PlanningResultStatus::kFailed;
    result.message = "planning failed";

    if (engine_succeeded) {
        if (outcome.status == PlanningOutcomeStatus::kSuccess) {
            try {
                const PlanningArtifactId artifact_id = planner.NextArtifactId();
                const ExecutionPlanId plan_id = planner.NextExecutionPlanId();

                auto artifact = std::make_unique<PlanningArtifact>(
                    artifact_id, session.GetId(), outcome.metadata,
                    outcome.artifact_payload);
                auto plan = std::make_unique<ExecutionPlan>(
                    plan_id, outcome.execution_plan_steps, outcome.metadata);

                // Replanning rule (Chapter 13): retire the session's
                // previously active artifact and its execution plan
                // atomically at linearization.
                for (const auto& key : planner.artifacts_.Enumerate()) {
                    PlanningArtifact* existing = planner.artifacts_.Find(key);
                    if (existing != nullptr && !existing->IsRetired() &&
                        existing->GetSessionId() == session.GetId()) {
                        existing->retired_ = true;
                    }
                }
                for (const auto& key : planner.execution_plans_.Enumerate()) {
                    ExecutionPlan* existing = planner.execution_plans_.Find(key);
                    if (existing != nullptr && !existing->IsRetired()) {
                        existing->retired_ = true;
                    }
                }

                planner.artifacts_.Register(artifact_id, std::move(artifact));
                planner.execution_plans_.Register(plan_id, std::move(plan));

                // Immutable Agent-owned snapshot (value copy).
                PlanningArtifactView view;
                view.artifact_id = artifact_id;
                view.session_id = session.GetId();
                view.metadata = outcome.metadata;
                view.execution_plan = ExecutionPlanSnapshot{
                    plan_id, outcome.execution_plan_steps, outcome.metadata};
                view.payload = outcome.artifact_payload;

                result.artifact_view = std::move(view);
                result.status = PlanningResultStatus::kSuccess;
                result.message = "planning completed";
            } catch (...) {
                // Result construction failure -> deterministic
                // terminal kFailed result; exactly-once preserved.
                result.status = PlanningResultStatus::kFailed;
                result.message = "result construction failure";
            }
        } else {
            result.message = "planning failed";
        }
    } else {
        result.message = "planning engine failure";
    }

    // Step 5e: exchange retirement (terminal result published).
    exchange->has_terminal_result_ = true;
    exchange->result_id_ = result.result_id;
    exchange->status_ = PlannerExchangeStatus::kRetired;

    // Step 5f: drain commit Planning -> Ready when no open
    // exchange remains.
    if (planner.lifecycle_ == PlannerLifecycleState::kPlanning &&
        session.OpenExchangeCount() == 0) {
        planner.lifecycle_ = PlannerLifecycleState::kReady;
    }

    return {PlanningCompletionStatus::kSuccess, "planning completed",
            std::move(result)};
}

LifecycleParticipationService::LifecycleParticipationService(Planner& owner) noexcept
    : owner_(&owner) {}

PlannerLifecycleResult LifecycleParticipationService::Initialize() {
    std::lock_guard<std::mutex> lock(owner_->mutex_);
    Planner& planner = *owner_;

    // Post-Terminated (and in-flight Terminating) availability:
    // every LifecycleParticipationService operation SHALL be
    // unavailable (AK0044 Revision A Section 7.3; P1-IS005
    // Rev5.1 Chapter 18.3).
    if (planner.lifecycle_ == PlannerLifecycleState::kTerminating ||
        planner.lifecycle_ == PlannerLifecycleState::kTerminated) {
        return {PlannerLifecycleResultStatus::kUnavailable,
                "planner not available in the current lifecycle state",
                planner.lifecycle_};
    }
    if (planner.lifecycle_ != PlannerLifecycleState::kCreated) {
        return {PlannerLifecycleResultStatus::kRejected,
                "Initialize is only valid from Created", planner.lifecycle_};
    }
    planner.lifecycle_ = PlannerLifecycleState::kInitializing;
    return {PlannerLifecycleResultStatus::kAccepted, "planner initialized",
            PlannerLifecycleState::kInitializing};
}

PlannerLifecycleResult LifecycleParticipationService::Activate() {
    std::lock_guard<std::mutex> lock(owner_->mutex_);
    Planner& planner = *owner_;

    // Post-Terminated (and in-flight Terminating) availability:
    // every LifecycleParticipationService operation SHALL be
    // unavailable (AK0044 Revision A Section 7.3; P1-IS005
    // Rev5.1 Chapter 18.3).
    if (planner.lifecycle_ == PlannerLifecycleState::kTerminating ||
        planner.lifecycle_ == PlannerLifecycleState::kTerminated) {
        return {PlannerLifecycleResultStatus::kUnavailable,
                "planner not available in the current lifecycle state",
                planner.lifecycle_};
    }
    if (planner.lifecycle_ != PlannerLifecycleState::kInitializing) {
        return {PlannerLifecycleResultStatus::kRejected,
                "Activate is only valid from Initializing", planner.lifecycle_};
    }
    if (planner.session_ != nullptr) {
        return {PlannerLifecycleResultStatus::kFailure,
                "primary session already exists", planner.lifecycle_};
    }
    try {
        planner.session_ = std::make_unique<PlannerSession>(
            MakePlannerSessionId(kPrimaryPlannerSessionIdValue));
    } catch (...) {
        return {PlannerLifecycleResultStatus::kFailure,
                "primary session creation failed", planner.lifecycle_};
    }
    planner.lifecycle_ = PlannerLifecycleState::kReady;
    return {PlannerLifecycleResultStatus::kAccepted, "planner activated",
            PlannerLifecycleState::kReady};
}

PlannerLifecycleResult LifecycleParticipationService::Suspend() {
    std::lock_guard<std::mutex> lock(owner_->mutex_);
    Planner& planner = *owner_;

    // Post-Terminated (and in-flight Terminating) availability:
    // every LifecycleParticipationService operation SHALL be
    // unavailable (AK0044 Revision A Section 7.3; P1-IS005
    // Rev5.1 Chapter 18.3).
    if (planner.lifecycle_ == PlannerLifecycleState::kTerminating ||
        planner.lifecycle_ == PlannerLifecycleState::kTerminated) {
        return {PlannerLifecycleResultStatus::kUnavailable,
                "planner not available in the current lifecycle state",
                planner.lifecycle_};
    }
    if (planner.lifecycle_ != PlannerLifecycleState::kPlanning) {
        return {PlannerLifecycleResultStatus::kRejected,
                "Suspend is only valid from Planning", planner.lifecycle_};
    }
    const std::size_t open =
        (planner.session_ != nullptr) ? planner.session_->OpenExchangeCount() : 0;
    if (open == 0) {
        return {PlannerLifecycleResultStatus::kBusy,
                "no active planning activity to suspend", planner.lifecycle_};
    }
    planner.lifecycle_ = PlannerLifecycleState::kSuspended;
    return {PlannerLifecycleResultStatus::kAccepted, "planner suspended",
            PlannerLifecycleState::kSuspended};
}

PlannerLifecycleResult LifecycleParticipationService::Resume() {
    std::lock_guard<std::mutex> lock(owner_->mutex_);
    Planner& planner = *owner_;

    // Post-Terminated (and in-flight Terminating) availability:
    // every LifecycleParticipationService operation SHALL be
    // unavailable (AK0044 Revision A Section 7.3; P1-IS005
    // Rev5.1 Chapter 18.3).
    if (planner.lifecycle_ == PlannerLifecycleState::kTerminating ||
        planner.lifecycle_ == PlannerLifecycleState::kTerminated) {
        return {PlannerLifecycleResultStatus::kUnavailable,
                "planner not available in the current lifecycle state",
                planner.lifecycle_};
    }
    if (planner.lifecycle_ != PlannerLifecycleState::kSuspended) {
        return {PlannerLifecycleResultStatus::kRejected,
                "Resume is only valid from Suspended", planner.lifecycle_};
    }
    planner.lifecycle_ = PlannerLifecycleState::kPlanning;
    return {PlannerLifecycleResultStatus::kAccepted, "planner resumed",
            PlannerLifecycleState::kPlanning};
}

PlannerLifecycleResult LifecycleParticipationService::Terminate() {
    std::lock_guard<std::mutex> lock(owner_->mutex_);
    Planner& planner = *owner_;
    switch (planner.lifecycle_) {
        case PlannerLifecycleState::kSuspended:
            return {PlannerLifecycleResultStatus::kRejected,
                    "termination is not permitted from Suspended; resume first",
                    planner.lifecycle_};
        case PlannerLifecycleState::kTerminating:
        case PlannerLifecycleState::kTerminated:
            return {PlannerLifecycleResultStatus::kUnavailable,
                    "planner already terminating/terminated", planner.lifecycle_};
        case PlannerLifecycleState::kCreated:
        case PlannerLifecycleState::kInitializing:
            return {PlannerLifecycleResultStatus::kRejected,
                    "planner is not operational", planner.lifecycle_};
        case PlannerLifecycleState::kReady:
        case PlannerLifecycleState::kPlanning:
            break;
    }

    const std::size_t open =
        (planner.session_ != nullptr) ? planner.session_->OpenExchangeCount() : 0;
    if (open != 0) {
        // Drain-before-terminate: no lifecycle mutation, all open
        // exchanges preserved.
        return {PlannerLifecycleResultStatus::kBusy,
                "open planning exchanges must drain before termination",
                planner.lifecycle_};
    }

    // Enter Terminating, then complete the mandatory shutdown
    // (Terminating -> Terminated) within the same serialized
    // operation, without Agent acknowledgement.
    planner.lifecycle_ = PlannerLifecycleState::kTerminating;

    // 1. Retire every Planner-owned PlanningArtifact and
    //    ExecutionPlan of the session (never resurrected).
    for (const auto& key : planner.artifacts_.Enumerate()) {
        PlanningArtifact* artifact = planner.artifacts_.Find(key);
        if (artifact != nullptr && !artifact->IsRetired()) {
            artifact->retired_ = true;
        }
    }
    for (const auto& key : planner.execution_plans_.Enumerate()) {
        ExecutionPlan* plan = planner.execution_plans_.Find(key);
        if (plan != nullptr && !plan->IsRetired()) {
            plan->retired_ = true;
        }
    }

    // 2. Retire the primary Planner Session.
    planner.session_.reset();

    // 3. Commit Terminating -> Terminated.
    planner.lifecycle_ = PlannerLifecycleState::kTerminated;

    return {PlannerLifecycleResultStatus::kAccepted, "planner terminated",
            PlannerLifecycleState::kTerminated};
}

PlannerInspectionService::PlannerInspectionService(const Planner& owner) noexcept
    : owner_(&owner) {}

PlannerInspectionResult PlannerInspectionService::GetOperationalState() const noexcept {
    std::lock_guard<std::mutex> lock(owner_->mutex_);
    PlannerInspectionResult result;
    result.operational = ProjectOperationalState(owner_->lifecycle_);
    if (owner_->lifecycle_ == PlannerLifecycleState::kTerminated) {
        // MIN-001: every Planner Service, including inspection,
        // SHALL be unavailable after Planner termination.
        result.status = PlannerInspectionStatus::kUnavailable;
        result.message = "planner terminated; inspection service unavailable";
    } else {
        result.status = PlannerInspectionStatus::kAvailable;
        result.message = "planner operational";
    }
    return result;
}

}  // namespace ak::planner
