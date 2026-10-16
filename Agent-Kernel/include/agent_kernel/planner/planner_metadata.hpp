// ============================================================
// Agent Kernel - PlanningMetadata (Planner boundary)
// ============================================================
// Planner-owned descriptive metadata (P1-IS005 Rev5.1 Chapter 8.1).
//
// Scope:
// - PlanningMetadata is a value type composed over the
//   P1-IS001 Foundation KernelMetadata neutral core.
// - Metadata carries no runtime behavior and no architectural
//   semantics; ownership of metadata remains with Planner.
// - Agent receives metadata only inside immutable snapshots.
//
// NON-responsibilities:
// - PlanningMetadata is not Runtime execution metadata and not a
//   lifecycle authority.
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include <agent_kernel/foundation/kernel_metadata.hpp>

namespace ak::planner {

struct PlanningMetadata {
    // Neutral core (Foundation value mechanics only).
    ak::KernelMetadata core;
    // Planning output version identifier.
    std::uint64_t version = 1;
    // Planning strategy identifier.
    std::string strategy;
    // Extensible, implementation-independent annotations.
    std::vector<std::string> annotations;

    // Value equality. Implemented manually (not defaulted) because
    // the Foundation KernelMetadata core is a neutral value with
    // no comparison operators; equality is field-by-field and
    // never observes architectural semantics.
    [[nodiscard]] bool operator==(const PlanningMetadata& other) const noexcept {
        return core.name == other.core.name &&
               core.label == other.core.label &&
               core.description == other.core.description &&
               core.tags == other.core.tags &&
               core.creationTime == other.core.creationTime &&
               version == other.version &&
               strategy == other.strategy &&
               annotations == other.annotations;
    }
    [[nodiscard]] bool operator!=(const PlanningMetadata& other) const noexcept {
        return !(*this == other);
    }
};

}  // namespace ak::planner
