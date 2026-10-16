// ============================================================
// Agent Kernel - ExecutionComposition (Agent boundary)
// ============================================================
// Agent-owned, Agent-coordinated execution-composition
// representation.
//
// P1-IS002 scope (Chapter 14 - Execution Composition):
// - Execution Composition is an Agent-owned implementation
//   responsibility, NOT an independent architectural
//   subsystem.
// - It MAY represent workflow composition, task composition,
//   dependency organization, sequencing, constraints,
//   execution metadata, and future Runtime request
//   preparation.
//
// NON-responsibilities (P1-IS002 Chapter 14.3):
// - It SHALL NOT execute Runtime Workflows or Tasks.
// - It SHALL NOT schedule Runtime Tasks.
// - It SHALL NOT resolve Runtime capabilities.
// - It SHALL NOT manage Runtime lifecycle.
// - It SHALL NOT publish Runtime execution events.
// - It SHALL NOT replace the Runtime Executor or Scheduler.
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

#include <agent_kernel/foundation/kernel_metadata.hpp>

namespace ak::agent {

// Kind of composition step represented by the Agent.
enum class CompositionStepKind : std::uint8_t {
    kWorkflowComposition = 0,
    kTaskComposition,
    kDependencyOrganization,
    kSequencing,
    kConstraint,
    kExecutionMetadata,
    kRuntimeRequestPreparation
};

// One step of the Agent-owned execution composition
// representation. All identifiers and metadata are Agent-owned
// representations; they are not Runtime objects.
struct CompositionStep {
    std::uint64_t id = 0;
    CompositionStepKind kind = CompositionStepKind::kWorkflowComposition;
    std::string description;
    std::vector<std::uint64_t> dependencies;
    std::vector<std::string> constraints;
    ak::KernelMetadata metadata;
};

// Agent-owned execution-composition representation.
class ExecutionComposition {
public:
    ExecutionComposition() = default;

    // Adds a step; returns the assigned step id (0 on failure).
    // A caller-supplied id is preserved when it is non-zero and
    // unique.
    [[nodiscard]] std::uint64_t AddStep(CompositionStep step);

    // Adds a dependency edge (step depends on dependsOn).
    // Both steps must exist and a step may not depend on itself.
    [[nodiscard]] bool AddDependency(std::uint64_t step,
                                     std::uint64_t dependsOn) noexcept;

    // Attaches a constraint to an existing step.
    [[nodiscard]] bool SetConstraint(std::uint64_t step,
                                     std::string constraint);

    // Sets Agent-owned execution metadata for the composition.
    void SetExecutionMetadata(ak::KernelMetadata metadata) {
        metadata_ = std::move(metadata);
    }

    [[nodiscard]] const ak::KernelMetadata& GetExecutionMetadata() const noexcept {
        return metadata_;
    }

    // -- Query --
    [[nodiscard]] std::size_t StepCount() const noexcept { return steps_.size(); }

    [[nodiscard]] bool HasStep(std::uint64_t id) const noexcept;

    [[nodiscard]] const std::vector<CompositionStep>& Steps() const noexcept {
        return steps_;
    }

    // Structural validation of the representation: all step ids
    // referenced by dependencies exist, no self-dependency, and
    // no dependency cycles. This validates the representation
    // only; it performs no Runtime action.
    [[nodiscard]] bool Validate() const;

private:
    std::vector<CompositionStep> steps_;
    ak::KernelMetadata metadata_;
    std::uint64_t next_step_id_ = 1;
};

}  // namespace ak::agent
