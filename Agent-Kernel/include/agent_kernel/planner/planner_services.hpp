// ============================================================
// Agent Kernel - PlannerServices (Planner boundary)
// ============================================================
// Planner Service boundary (P1-IS005 Rev5.1 Chapter 7.2;
// AK0044 Revision A Section 7).
//
// Three services realize the three minimum service categories:
// - PlanningService: submission and the sole completion path.
// - LifecycleParticipationService: lifecycle participation
//   requests; Planner remains the sole lifecycle authority.
// - PlannerInspectionService: read-only observation of the
//   Operational State projection; unavailable after Terminated
//   (MIN-001; AK0044 Revision A Section 7.3).
//
// NON-responsibilities:
// - Services do not coordinate Agent, Memory, Context, Tool, or
//   Runtime; they expose no mutable Planner internals.
// ============================================================

#pragma once

#include <cstdint>
#include <string_view>

#include <agent_kernel/planner/planner_result.hpp>
#include <agent_kernel/planner/planning_request.hpp>

namespace ak::planner {

class Planner;

// ------------------------------------------------------------
// PlanningService (Planning Capability Service)
// ------------------------------------------------------------
class PlanningService {
public:
    // Submits an Agent-owned immutable request (value copy into
    // Planner-owned processing state).
    [[nodiscard]] PlanningAcceptance Submit(const PlanningRequest& request);

    // Sole completion/delivery path (exactly-once; one
    // serialization boundary).
    [[nodiscard]] PlanningCompletionResult CompletePlanningExchange(
        const PlanningRequestId& request_id);

private:
    friend class Planner;
    explicit PlanningService(Planner& owner) noexcept;
    Planner* owner_ = nullptr;
};

// ------------------------------------------------------------
// LifecycleParticipationService
// ------------------------------------------------------------
class LifecycleParticipationService {
public:
    [[nodiscard]] PlannerLifecycleResult Initialize();  // Created -> Initializing
    [[nodiscard]] PlannerLifecycleResult Activate();    // Initializing -> Ready (+ primary session)
    [[nodiscard]] PlannerLifecycleResult Suspend();     // Planning -> Suspended (open>0)
    [[nodiscard]] PlannerLifecycleResult Resume();      // Suspended -> Planning
    [[nodiscard]] PlannerLifecycleResult Terminate();   // Ready/Planning -> Terminating -> Terminated (drain)

private:
    friend class Planner;
    explicit LifecycleParticipationService(Planner& owner) noexcept;
    Planner* owner_ = nullptr;
};

// ------------------------------------------------------------
// PlannerInspectionService
// ------------------------------------------------------------
class PlannerInspectionService {
public:
    // Read-only observation of the Operational State projection
    // (the ONLY observation target, AK0044 Revision A Section
    // 7.2). SHALL return kAvailable with the deterministic
    // projection in every non-Terminated state, and SHALL
    // return kUnavailable after Terminated (MIN-001).
    [[nodiscard]] PlannerInspectionResult GetOperationalState() const noexcept;

private:
    friend class Planner;
    explicit PlannerInspectionService(const Planner& owner) noexcept;
    const Planner* owner_ = nullptr;
};

}  // namespace ak::planner
