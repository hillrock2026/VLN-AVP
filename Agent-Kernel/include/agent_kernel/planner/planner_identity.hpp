// ============================================================
// Agent Kernel - PlannerIdentity (Planner boundary)
// ============================================================
// Planner-owned identity domains (P1-IS005 Rev5.1 Chapter 5).
//
// Scope:
// - Six typed identity domains, all derived from the P1-IS001
//   Foundation TypedKernelIdentity; cross-domain assignment is
//   a compile-time error.
// - A default-constructed identity is invalid (value 0).
// - PlannerIdentity is created by the production composition;
//   PlanningRequestId is created by the Agent; all other
//   identities are created by the Planner.
//
// NON-responsibilities:
// - Identities carry no ownership, no lifecycle, and no Runtime
//   semantics; identity never transfers architectural ownership.
// ============================================================

#pragma once

#include <cstdint>

#include <agent_kernel/foundation/kernel_identity.hpp>

namespace ak::planner {

struct PlannerIdentityTag {};
struct PlannerSessionTag {};
struct PlanningRequestTag {};
struct PlanningResultTag {};
struct PlanningArtifactTag {};
struct ExecutionPlanTag {};

// Planner-owned identity domains.
using PlannerIdentity = ak::TypedKernelIdentity<PlannerIdentityTag>;
using PlannerSessionId = ak::TypedKernelIdentity<PlannerSessionTag>;
using PlanningRequestId = ak::TypedKernelIdentity<PlanningRequestTag>;
using PlanningResultId = ak::TypedKernelIdentity<PlanningResultTag>;
using PlanningArtifactId = ak::TypedKernelIdentity<PlanningArtifactTag>;
using ExecutionPlanId = ak::TypedKernelIdentity<ExecutionPlanTag>;

// Creates valid Planner identities. Default construction yields
// an invalid identity (value 0).
[[nodiscard]] inline PlannerIdentity MakePlannerIdentity(std::uint64_t value) noexcept {
    return PlannerIdentity(value);
}
[[nodiscard]] inline PlannerSessionId MakePlannerSessionId(std::uint64_t value) noexcept {
    return PlannerSessionId(value);
}
[[nodiscard]] inline PlanningRequestId MakePlanningRequestId(std::uint64_t value) noexcept {
    return PlanningRequestId(value);
}
[[nodiscard]] inline PlanningResultId MakePlanningResultId(std::uint64_t value) noexcept {
    return PlanningResultId(value);
}
[[nodiscard]] inline PlanningArtifactId MakePlanningArtifactId(std::uint64_t value) noexcept {
    return PlanningArtifactId(value);
}
[[nodiscard]] inline ExecutionPlanId MakeExecutionPlanId(std::uint64_t value) noexcept {
    return ExecutionPlanId(value);
}

// Phase 3: exactly one primary Planner Session per Planner
// instance, created at Activate; its identity value is the
// deterministic constant below (implementation constant,
// documented for request construction and tests).
inline constexpr std::uint64_t kPrimaryPlannerSessionIdValue = 1;

}  // namespace ak::planner

// ============================================================
// std::hash specializations
// ============================================================
namespace std {
template <>
struct hash<ak::planner::PlannerIdentity> {
    size_t operator()(const ak::planner::PlannerIdentity& id) const noexcept {
        return hash<ak::KernelIdentity>()(id);
    }
};
template <>
struct hash<ak::planner::PlannerSessionId> {
    size_t operator()(const ak::planner::PlannerSessionId& id) const noexcept {
        return hash<ak::KernelIdentity>()(id);
    }
};
template <>
struct hash<ak::planner::PlanningRequestId> {
    size_t operator()(const ak::planner::PlanningRequestId& id) const noexcept {
        return hash<ak::KernelIdentity>()(id);
    }
};
template <>
struct hash<ak::planner::PlanningResultId> {
    size_t operator()(const ak::planner::PlanningResultId& id) const noexcept {
        return hash<ak::KernelIdentity>()(id);
    }
};
template <>
struct hash<ak::planner::PlanningArtifactId> {
    size_t operator()(const ak::planner::PlanningArtifactId& id) const noexcept {
        return hash<ak::KernelIdentity>()(id);
    }
};
template <>
struct hash<ak::planner::ExecutionPlanId> {
    size_t operator()(const ak::planner::ExecutionPlanId& id) const noexcept {
        return hash<ak::KernelIdentity>()(id);
    }
};

}  // namespace std
