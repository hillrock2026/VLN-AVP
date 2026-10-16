// ============================================================
// Agent Kernel - PlannerState (Planner boundary)
// ============================================================
// Planner lifecycle and operational state (P1-IS005 Rev5.1
// Chapter 6; AK0044 Revision A Chapters 4-5).
//
// Lifecycle (normative, locked):
//   Created -> Initializing -> Ready <-> Planning <-> Suspended
//   Ready/Planning -> Terminating -> Terminated (drain-before-
//   terminate admission; mandatory shutdown).
//
// Operational State is a distinct typed 1:1 total deterministic
// projection of lifecycle state; it is NOT an independent state
// machine and has no transitions.
//
// NON-responsibilities:
// - These models are Planner-owned; no other subsystem owns or
//   drives them. Runtime remains unaware of Planner state.
// ============================================================

#pragma once

#include <cstddef>
#include <cstdint>
#include <string_view>

#include <agent_kernel/foundation/kernel_lifecycle.hpp>

namespace ak::planner {

// ------------------------------------------------------------
// Planner lifecycle state model (AK0044 Revision A Section 4.1)
// ------------------------------------------------------------
enum class PlannerLifecycleState : std::uint8_t {
    kCreated = 0,
    kInitializing,
    kReady,
    kPlanning,
    kSuspended,
    kTerminating,
    kTerminated
};

[[nodiscard]] constexpr std::string_view PlannerLifecycleStateName(
    PlannerLifecycleState state) noexcept {
    switch (state) {
        case PlannerLifecycleState::kCreated:
            return "Created";
        case PlannerLifecycleState::kInitializing:
            return "Initializing";
        case PlannerLifecycleState::kReady:
            return "Ready";
        case PlannerLifecycleState::kPlanning:
            return "Planning";
        case PlannerLifecycleState::kSuspended:
            return "Suspended";
        case PlannerLifecycleState::kTerminating:
            return "Terminating";
        case PlannerLifecycleState::kTerminated:
            return "Terminated";
    }
    return "Unknown";
}

[[nodiscard]] constexpr std::uint8_t PlannerLifecycleStateCode(
    PlannerLifecycleState state) noexcept {
    return static_cast<std::uint8_t>(state);
}

[[nodiscard]] inline ak::LifecycleState ToLifecycleState(
    PlannerLifecycleState state) noexcept {
    return ak::LifecycleState(PlannerLifecycleStateCode(state));
}

// ------------------------------------------------------------
// Planner operational state model (typed projection, AK0044
// Revision A Section 5.1)
// ------------------------------------------------------------
enum class PlannerOperationalState : std::uint8_t {
    kCreated = 0,
    kInitializing,
    kReady,
    kPlanning,
    kSuspended,
    kTerminating,
    kTerminated
};

[[nodiscard]] constexpr std::string_view PlannerOperationalStateName(
    PlannerOperationalState state) noexcept {
    switch (state) {
        case PlannerOperationalState::kCreated:
            return "Created";
        case PlannerOperationalState::kInitializing:
            return "Initializing";
        case PlannerOperationalState::kReady:
            return "Ready";
        case PlannerOperationalState::kPlanning:
            return "Planning";
        case PlannerOperationalState::kSuspended:
            return "Suspended";
        case PlannerOperationalState::kTerminating:
            return "Terminating";
        case PlannerOperationalState::kTerminated:
            return "Terminated";
    }
    return "Unknown";
}

// Total deterministic projection: lifecycle -> operational (1:1).
[[nodiscard]] constexpr PlannerOperationalState ProjectOperationalState(
    PlannerLifecycleState lifecycle) noexcept {
    return static_cast<PlannerOperationalState>(PlannerLifecycleStateCode(lifecycle));
}

// ------------------------------------------------------------
// Normative lifecycle transitions (AK0044 Revision A Section 4.3)
// ------------------------------------------------------------
[[nodiscard]] constexpr bool IsLegalPlannerLifecycleTransition(
    PlannerLifecycleState from, PlannerLifecycleState to) noexcept {
    switch (from) {
        case PlannerLifecycleState::kCreated:
            return to == PlannerLifecycleState::kInitializing;
        case PlannerLifecycleState::kInitializing:
            return to == PlannerLifecycleState::kReady;
        case PlannerLifecycleState::kReady:
            return to == PlannerLifecycleState::kPlanning ||
                   to == PlannerLifecycleState::kTerminating;
        case PlannerLifecycleState::kPlanning:
            return to == PlannerLifecycleState::kReady ||
                   to == PlannerLifecycleState::kSuspended ||
                   to == PlannerLifecycleState::kTerminating;
        case PlannerLifecycleState::kSuspended:
            return to == PlannerLifecycleState::kPlanning;
        case PlannerLifecycleState::kTerminating:
            return to == PlannerLifecycleState::kTerminated;
        case PlannerLifecycleState::kTerminated:
            return false;
    }
    return false;
}

// Foundation-neutral rule adapter.
[[nodiscard]] bool PlannerLifecycleTransitionRule(std::uint8_t from,
                                                  std::uint8_t to) noexcept;

// Validates a requested lifecycle transition. The Foundation
// validator only validates; Planner owns and initiates every
// transition.
[[nodiscard]] ak::TransitionResult ValidatePlannerLifecycleTransition(
    PlannerLifecycleState from, PlannerLifecycleState to) noexcept;

// ------------------------------------------------------------
// PlannerState - read-only state summary value (P1-IS005
// Rev5.1 Chapter 6.4)
// ------------------------------------------------------------
struct PlannerState {
    PlannerLifecycleState lifecycle = PlannerLifecycleState::kCreated;
    PlannerOperationalState operational = PlannerOperationalState::kCreated;
    std::size_t open_exchange_count = 0;
    std::size_t active_artifact_count = 0;
    std::size_t session_count = 0;

    [[nodiscard]] bool operator==(const PlannerState&) const noexcept = default;
};

}  // namespace ak::planner
