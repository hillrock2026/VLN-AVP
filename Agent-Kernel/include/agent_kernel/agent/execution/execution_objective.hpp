// ============================================================
// Agent Kernel - ExecutionObjective (Agent boundary)
// ============================================================
// Agent-owned execution objective representation.
//
// P1-IS002 scope (Chapter 8.1 - Execution Objective
// Management):
// - Execution objectives represent desired intelligent
//   outcomes owned by the Agent.
// - They SHALL NOT be confused with Runtime execution
//   objects, Scheduler requests, Task execution state, or
//   Workflow execution state.
//
// NON-responsibilities:
// - This representation is not a Runtime object and includes
//   no Runtime type.
// - Objective status is an internal Agent-owned detail; it is
//   NOT an architectural state of the Agent (the architectural
//   state model remains the single externally visible model).
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include <agent_kernel/foundation/kernel_identity.hpp>
#include <agent_kernel/foundation/kernel_metadata.hpp>

namespace ak::agent {

// Owner-scoped identity tag for execution objectives.
struct ExecutionObjectiveTag {};

using ObjectiveId = ak::TypedKernelIdentity<ExecutionObjectiveTag>;

// Internal, Agent-owned status of an execution objective.
// This is NOT an architectural state: it never replaces the
// single externally visible Agent state model.
enum class ObjectiveStatus : std::uint8_t {
    kProposed = 0,
    kAccepted,
    kInProgress,
    kEvaluated
};

[[nodiscard]] constexpr std::string_view ObjectiveStatusName(ObjectiveStatus status) noexcept {
    switch (status) {
        case ObjectiveStatus::kProposed:
            return "Proposed";
        case ObjectiveStatus::kAccepted:
            return "Accepted";
        case ObjectiveStatus::kInProgress:
            return "InProgress";
        case ObjectiveStatus::kEvaluated:
            return "Evaluated";
    }
    return "Unknown";
}

// Agent-owned execution objective value representation.
class ExecutionObjective {
public:
    ExecutionObjective() = default;
    ExecutionObjective(ObjectiveId id, std::string description)
        : id_(id), description_(std::move(description)) {}

    // -- Identity --
    [[nodiscard]] ObjectiveId GetId() const noexcept { return id_; }

    // -- Description and criteria --
    [[nodiscard]] const std::string& GetDescription() const noexcept {
        return description_;
    }

    void AddCriterion(std::string criterion) {
        criteria_.push_back(std::move(criterion));
    }

    [[nodiscard]] const std::vector<std::string>& Criteria() const noexcept {
        return criteria_;
    }

    // -- Neutral metadata --
    void SetExecutionMetadata(ak::KernelMetadata metadata) {
        metadata_ = std::move(metadata);
    }

    [[nodiscard]] const ak::KernelMetadata& GetExecutionMetadata() const noexcept {
        return metadata_;
    }

    // -- Internal status (Agent-owned; not architectural state) --
    [[nodiscard]] ObjectiveStatus GetStatus() const noexcept { return status_; }

    void Accept() noexcept { status_ = ObjectiveStatus::kAccepted; }
    void MarkInProgress() noexcept { status_ = ObjectiveStatus::kInProgress; }
    void MarkEvaluated() noexcept { status_ = ObjectiveStatus::kEvaluated; }

private:
    ObjectiveId id_;
    std::string description_;
    std::vector<std::string> criteria_;
    ak::KernelMetadata metadata_;
    ObjectiveStatus status_ = ObjectiveStatus::kProposed;
};

}  // namespace ak::agent
