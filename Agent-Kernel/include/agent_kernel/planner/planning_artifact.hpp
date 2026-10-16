// ============================================================
// Agent Kernel - PlanningArtifact (Planner boundary)
// ============================================================
// Planner-owned planning outputs and their immutable Agent-owned
// snapshots (P1-IS005 Rev5.1 Chapter 8; AK0044 Revision A
// Section 10).
//
// Ownership:
// - PlanningArtifact and ExecutionPlan remain Planner-owned
//   throughout their architectural lifetime; ownership never
//   transfers to Agent or Runtime.
// - PlanningArtifactView and ExecutionPlanSnapshot are immutable
//   Agent-owned value snapshots delivered at completion; they
//   preserve artifact identity and remain readable after Planner
//   termination.
//
// NON-responsibilities:
// - These are not Workflow, Task, Scheduler, Executor, Runtime
//   request, or Runtime execution objects; no cast or mutation
//   may convert them into Runtime-owned objects.
// ============================================================

#pragma once

#include <string>
#include <vector>

#include <agent_kernel/planner/planner_identity.hpp>
#include <agent_kernel/planner/planner_metadata.hpp>

namespace ak::planner {

// ------------------------------------------------------------
// Planner-owned artifact
// ------------------------------------------------------------
class PlanningArtifact {
public:
    PlanningArtifact(PlanningArtifactId id, PlannerSessionId session_id,
                     PlanningMetadata metadata, std::string payload);

    [[nodiscard]] PlanningArtifactId GetId() const noexcept { return id_; }
    [[nodiscard]] PlannerSessionId GetSessionId() const noexcept { return session_id_; }
    [[nodiscard]] const PlanningMetadata& GetMetadata() const noexcept {
        return metadata_;
    }
    [[nodiscard]] const std::string& Payload() const noexcept { return payload_; }
    [[nodiscard]] bool IsRetired() const noexcept { return retired_; }

private:
    friend class PlanningService;
    friend class LifecycleParticipationService;
    PlanningArtifactId id_;
    PlannerSessionId session_id_;
    PlanningMetadata metadata_;
    std::string payload_;
    bool retired_ = false;   // true after replanning/termination retirement
};

// ------------------------------------------------------------
// Planner-owned execution plan
// ------------------------------------------------------------
class ExecutionPlan {
public:
    ExecutionPlan(ExecutionPlanId id, std::vector<std::string> steps,
                  PlanningMetadata metadata);

    [[nodiscard]] ExecutionPlanId GetId() const noexcept { return id_; }
    [[nodiscard]] const std::vector<std::string>& Steps() const noexcept {
        return steps_;
    }
    [[nodiscard]] const PlanningMetadata& GetMetadata() const noexcept {
        return metadata_;
    }
    [[nodiscard]] bool IsRetired() const noexcept { return retired_; }

private:
    friend class PlanningService;
    friend class LifecycleParticipationService;
    ExecutionPlanId id_;
    std::vector<std::string> steps_;
    PlanningMetadata metadata_;
    bool retired_ = false;
};

// ------------------------------------------------------------
// Immutable Agent-owned snapshots (value copies)
// ------------------------------------------------------------
struct ExecutionPlanSnapshot {
    ExecutionPlanId execution_plan_id;
    std::vector<std::string> steps;
    PlanningMetadata metadata;

    [[nodiscard]] bool operator==(const ExecutionPlanSnapshot&) const noexcept = default;
    [[nodiscard]] bool operator!=(const ExecutionPlanSnapshot&) const noexcept = default;
};

struct PlanningArtifactView {
    PlanningArtifactId artifact_id;      // preserves artifact identity
    PlannerSessionId session_id;
    PlanningMetadata metadata;           // immutable metadata snapshot
    ExecutionPlanSnapshot execution_plan; // immutable execution-plan snapshot
    std::string payload;                 // immutable planning output content

    [[nodiscard]] bool operator==(const PlanningArtifactView&) const noexcept = default;
    [[nodiscard]] bool operator!=(const PlanningArtifactView&) const noexcept = default;
};

}  // namespace ak::planner
