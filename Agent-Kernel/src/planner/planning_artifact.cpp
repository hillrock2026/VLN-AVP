// ============================================================
// Agent Kernel - PlanningArtifact (Planner boundary)
// ============================================================
// Implementation of the Planner-owned artifact and execution
// plan objects.
// ============================================================

#include <agent_kernel/planner/planning_artifact.hpp>

#include <utility>

namespace ak::planner {

PlanningArtifact::PlanningArtifact(PlanningArtifactId id, PlannerSessionId session_id,
                                   PlanningMetadata metadata, std::string payload)
    : id_(id),
      session_id_(session_id),
      metadata_(std::move(metadata)),
      payload_(std::move(payload)) {}

ExecutionPlan::ExecutionPlan(ExecutionPlanId id, std::vector<std::string> steps,
                             PlanningMetadata metadata)
    : id_(id),
      steps_(std::move(steps)),
      metadata_(std::move(metadata)) {}

}  // namespace ak::planner
