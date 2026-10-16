// ============================================================
// test_doubles.hpp - P1-IS005 Planner test doubles
// ============================================================
// Standard test fixtures and failure-injection engines
// (P1-IS005 Rev5.1 Chapter 20.9). The doubles carry no Planner
// ownership, no lifecycle authority, and no Runtime reference.
// ============================================================

#pragma once

#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>

#include <agent_kernel/planner/planner.hpp>
#include <agent_kernel/planner/planning_engine.hpp>
#include <agent_kernel/planner/planning_request.hpp>

namespace ak::planner {
namespace test {

// ------------------------------------------------------------
// StagedPlanningEngine: per-request readiness flag map;
// MarkReady(request_id) makes HasOutcome true. Used to test
// kPending and exactly-once determinism.
// ------------------------------------------------------------
class StagedPlanningEngine final : public IPlanningEngine {
public:
    void MarkReady(const PlannerSessionId& session_id,
                   const PlanningRequestId& request_id) {
        ready_.emplace(Key{session_id, request_id}, true);
    }

    [[nodiscard]] bool HasOutcome(const PlannerSessionId& session_id,
                                  const PlanningRequestId& request_id) const noexcept override {
        return ready_.find(Key{session_id, request_id}) != ready_.end();
    }

    [[nodiscard]] PlanningOutcome Outcome(const PlannerSessionId&,
                                          const PlanningRequest& request) noexcept override {
        PlanningOutcome outcome;
        outcome.status = PlanningOutcomeStatus::kSuccess;
        outcome.metadata.version = 1;
        outcome.metadata.strategy = "staged";
        outcome.execution_plan_steps.push_back(request.goal);
        outcome.artifact_payload = request.goal;
        outcome.message = "planning completed";
        return outcome;
    }

private:
    struct Key {
        PlannerSessionId session_id;
        PlanningRequestId request_id;
        bool operator<(const Key& other) const noexcept {
            if (session_id != other.session_id) {
                return session_id < other.session_id;
            }
            return request_id < other.request_id;
        }
    };
    std::map<Key, bool> ready_;
};

// ------------------------------------------------------------
// FailingPlanningEngine: HasOutcome always true; Outcome produces
// a deterministic kFailed outcome ("injected failure").
// ------------------------------------------------------------
class FailingPlanningEngine final : public IPlanningEngine {
public:
    [[nodiscard]] bool HasOutcome(const PlannerSessionId&,
                                  const PlanningRequestId&) const noexcept override {
        return true;
    }

    [[nodiscard]] PlanningOutcome Outcome(const PlannerSessionId&,
                                          const PlanningRequest&) noexcept override {
        PlanningOutcome outcome;
        outcome.status = PlanningOutcomeStatus::kFailed;
        outcome.message = "injected failure";
        return outcome;
    }
};

// ------------------------------------------------------------
// ThrowingPlanningEngine: Outcome throws; used to test the
// serialization-boundary exception conversion to a terminal
// kFailed result.
// ------------------------------------------------------------
// Throws the injected engine failure from a non-noexcept helper.
//
// NOTE ON C++ SEMANTICS: IPlanningEngine::Outcome is declared
// noexcept (P1-IS005 Rev5.1 Chapter 11.1). A genuine noexcept
// contract violation terminates the process (std::terminate)
// BEFORE any catch can observe it; therefore this double exists
// to document the contract-violation boundary and is never
// invoked by the conformance suite (see the exactly-once test
// group). The Planner's defensive catch at the serialization
// boundary covers the catchable failure classes (result
// construction), and deterministic failure outcomes are tested
// via FailingPlanningEngine.
[[noreturn]] inline void ThrowInjectedEngineFailure() {
    throw std::runtime_error("injected engine failure");
}

class ThrowingPlanningEngine final : public IPlanningEngine {
public:
    [[nodiscard]] bool HasOutcome(const PlannerSessionId&,
                                  const PlanningRequestId&) const noexcept override {
        return true;
    }

    [[nodiscard]] PlanningOutcome Outcome(const PlannerSessionId&,
                                          const PlanningRequest&) noexcept override {
        ThrowInjectedEngineFailure();
        return PlanningOutcome{};
    }
};

// ------------------------------------------------------------
// PlannerTestFixture: constructs a Planner with a configurable
// engine and exposes the primary session id. The engine MUST
// outlive the fixture (declare the engine first).
// ------------------------------------------------------------
class PlannerTestFixture {
public:
    explicit PlannerTestFixture(IPlanningEngine& engine)
        : planner_(MakePlannerIdentity(42), engine) {}

    [[nodiscard]] Planner& planner() noexcept { return planner_; }
    [[nodiscard]] const Planner& planner() const noexcept { return planner_; }

    [[nodiscard]] PlannerSessionId PrimarySessionId() const noexcept {
        return MakePlannerSessionId(kPrimaryPlannerSessionIdValue);
    }

    [[nodiscard]] PlanningRequest MakeRequest(std::uint64_t id,
                                              std::string goal = "planning goal") const {
        PlanningRequest request;
        request.request_id = MakePlanningRequestId(id);
        request.session_id = PrimarySessionId();
        request.metadata.version = 1;
        request.goal = std::move(goal);
        return request;
    }

    // Fully activates the planner (Created -> Initializing ->
    // Ready) through the real lifecycle participation service.
    void ActivatePlanner() {
        static_cast<void>(planner_.LifecycleContract().Lifecycle().Initialize());
        static_cast<void>(planner_.LifecycleContract().Lifecycle().Activate());
    }

private:
    Planner planner_;
};

}  // namespace test
}  // namespace ak::planner
