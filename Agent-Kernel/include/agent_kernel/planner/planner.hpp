// ============================================================
// Agent Kernel - Planner (Planner boundary)
// ============================================================
// Planner root object (P1-IS005 Rev5.1 Chapter 7.1; AK0044
// Revision A Section 7).
//
// The Planner root owns:
//   - Planner identity;
//   - the Planner lifecycle machine;
//   - the primary Planner Session (exchange registry);
//   - the Planning Artifact registry;
//   - the Execution Plan registry;
//   - the three Planner Services;
//   - the two Agent-facing contracts;
//   - the extension boundary;
//   - the engine reference (non-owning; engine lifetime >=
//     Planner lifetime);
//   - the single synchronization boundary (one std::mutex).
//
// NON-responsibilities:
// - Planner never includes ak::agent headers, never coordinates
//   Agent/Memory/Context/Tool, and performs no Runtime action.
// - Root state accessors are the Planner's own state
//   representation, not Planner Services, and are the ONLY
//   post-terminated state observation path (MIN-001).
// ============================================================

#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include <agent_kernel/foundation/kernel_metadata.hpp>
#include <agent_kernel/foundation/kernel_registry.hpp>
#include <agent_kernel/planner/planner_contracts.hpp>
#include <agent_kernel/planner/planner_extensions.hpp>
#include <agent_kernel/planner/planner_identity.hpp>
#include <agent_kernel/planner/planner_metadata.hpp>
#include <agent_kernel/planner/planner_services.hpp>
#include <agent_kernel/planner/planner_state.hpp>
#include <agent_kernel/planner/planning_artifact.hpp>
#include <agent_kernel/planner/planning_engine.hpp>
#include <agent_kernel/planner/planning_request.hpp>
#include <agent_kernel/planner/planner_session.hpp>

namespace ak::planner {

struct PlannerConfiguration {
    ak::KernelMetadata metadata;   // descriptive only; no architectural semantics
};

class Planner {
public:
    Planner(PlannerIdentity identity, IPlanningEngine& engine,
            PlannerConfiguration configuration = {});
    // non-copyable, non-movable (owns services composed on
    // internal state and the single synchronization boundary)
    Planner(const Planner&) = delete;
    Planner& operator=(const Planner&) = delete;
    Planner(Planner&&) = delete;
    Planner& operator=(Planner&&) = delete;

    // -- Identity --
    [[nodiscard]] PlannerIdentity GetIdentity() const noexcept;

    // -- State representation (read-only, always callable) --
    [[nodiscard]] PlannerLifecycleState GetLifecycleState() const noexcept;
    [[nodiscard]] PlannerOperationalState GetOperationalState() const noexcept;
    [[nodiscard]] std::size_t OpenExchangeCount() const noexcept;
    [[nodiscard]] PlannerState GetState() const noexcept;

    // -- Agent-facing contracts (Planner-owned) --
    [[nodiscard]] PlannerAgentContract& AgentContract() noexcept;
    [[nodiscard]] const PlannerAgentContract& AgentContract() const noexcept;
    [[nodiscard]] PlannerLifecycleContract& LifecycleContract() noexcept;
    [[nodiscard]] const PlannerLifecycleContract& LifecycleContract() const noexcept;

    // -- Services --
    [[nodiscard]] PlannerInspectionService& Inspection() noexcept;
    [[nodiscard]] const PlannerInspectionService& Inspection() const noexcept;

    // -- Extensions --
    [[nodiscard]] PlannerExtensionBoundary& Extensions() noexcept;
    [[nodiscard]] const PlannerExtensionBoundary& Extensions() const noexcept;

private:
    friend class PlanningService;
    friend class LifecycleParticipationService;
    friend class PlannerInspectionService;
    friend class PlannerAgentContract;
    friend class PlannerLifecycleContract;

    // Serialized helpers used by the Planner Services (friends).
    [[nodiscard]] std::size_t CountActiveArtifactsLocked() const noexcept;
    [[nodiscard]] PlanningResultId NextResultId() noexcept;
    [[nodiscard]] PlanningArtifactId NextArtifactId() noexcept;
    [[nodiscard]] ExecutionPlanId NextExecutionPlanId() noexcept;

    // Owned internal state. Member order: identity, engine
    // reference, single synchronization boundary, lifecycle,
    // primary session, artifact/execution-plan registries,
    // services, contracts, extension boundary, configuration,
    // identity-value counters.
    PlannerIdentity identity_;
    IPlanningEngine* engine_ = nullptr;
    mutable std::mutex mutex_;   // single synchronization boundary
    PlannerLifecycleState lifecycle_ = PlannerLifecycleState::kCreated;
    std::unique_ptr<PlannerSession> session_;   // created at Activate
    ak::OwnerScopedRegistry<PlanningArtifactId, PlanningArtifact> artifacts_;
    ak::OwnerScopedRegistry<ExecutionPlanId, ExecutionPlan> execution_plans_;
    PlanningService planning_service_;
    LifecycleParticipationService lifecycle_service_;
    PlannerInspectionService inspection_service_;
    PlannerAgentContract agent_contract_;
    PlannerLifecycleContract lifecycle_contract_;
    PlannerExtensionBoundary extensions_;
    PlannerConfiguration configuration_;
    std::uint64_t next_result_value_ = 1;
    std::uint64_t next_artifact_value_ = 1;
    std::uint64_t next_execution_plan_value_ = 1;
};

}  // namespace ak::planner
