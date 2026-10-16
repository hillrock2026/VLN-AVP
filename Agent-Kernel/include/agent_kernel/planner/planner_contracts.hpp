// ============================================================
// Agent Kernel - PlannerContracts (Planner boundary)
// ============================================================
// Planner-Agent contracts (P1-IS005 Rev5.1 Chapter 14;
// AK0044 Revision A Section 11).
//
// Two architecturally separate contracts:
// - PlannerAgentContract (Planning Capability Contract): carries
//   ONLY planning request/result semantics.
// - PlannerLifecycleContract (Lifecycle Participation Contract):
//   carries ONLY lifecycle participation operations.
//
// Both contracts are Planner-owned; the Agent is the invoker;
// the Planner is the implementation owner. Neither is a second
// lifecycle authority. Dependency direction remains
// Agent -> Planner Coordination Boundary -> Planner.
//
// NON-responsibilities:
// - These contracts are not a competing planning API and carry
//   no Runtime semantics; the generic Phase 1 IPlannerContract
//   (ak::agent) remains unchanged (Chapter 14.4).
// ============================================================

#pragma once

#include <string_view>

#include <agent_kernel/planner/planner_services.hpp>

namespace ak::planner {

class Planner;

// ------------------------------------------------------------
// PlannerAgentContract - Planning Capability Contract
// ------------------------------------------------------------
class PlannerAgentContract {
public:
    explicit PlannerAgentContract(Planner& planner) noexcept : planner_(&planner) {}

    [[nodiscard]] std::string_view ContractName() const noexcept { return "Planner"; }

    // Sole planning capability surface (Submit -> Acceptance ->
    // Activity -> Result).
    [[nodiscard]] PlanningService& Planning() noexcept;
    [[nodiscard]] const PlanningService& Planning() const noexcept;

private:
    Planner* planner_ = nullptr;
};

// ------------------------------------------------------------
// PlannerLifecycleContract - Lifecycle Participation Contract
// ------------------------------------------------------------
class PlannerLifecycleContract {
public:
    explicit PlannerLifecycleContract(Planner& planner) noexcept : planner_(&planner) {}

    [[nodiscard]] std::string_view ContractName() const noexcept {
        return "PlannerLifecycle";
    }

    // Lifecycle participation surface ONLY: Agent requests a
    // lifecycle operation; Planner remains the sole authority.
    [[nodiscard]] LifecycleParticipationService& Lifecycle() noexcept;
    [[nodiscard]] const LifecycleParticipationService& Lifecycle() const noexcept;

private:
    Planner* planner_ = nullptr;
};

}  // namespace ak::planner
