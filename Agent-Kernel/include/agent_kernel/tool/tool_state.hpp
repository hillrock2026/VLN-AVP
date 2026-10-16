// ============================================================
// Agent Kernel - Tool State (Tool boundary)
// ============================================================
// P1-IS006 Rev2 Chapters 9 and 11 - Tool lifecycle and
// operational state.
//
// - ToolLifecycleState is Tool-owned lifecycle authority
//   (TOL-017); kRetired is terminal (TOL-027).
// - ToolOperationalState is Tool-owned and separate from
//   lifecycle state (TOL-029, TOL-030, TOL-031).
// - kRestricted is entered/exited under TOL-094..TOL-097.
//
// NON-responsibilities:
// - Neither state model represents Runtime execution state.
// ============================================================

#pragma once

#include <cstdint>

namespace ak::tool {

// Tool lifecycle (Chapter 9.1). kRetired is terminal.
enum class ToolLifecycleState : std::uint8_t {
    kInitializing = 0,
    kRegistered,
    kAvailable,
    kSuspended,
    kRetiring,
    kRetired
};

// Tool operational state (Chapter 11). Distinct from lifecycle.
enum class ToolOperationalState : std::uint8_t {
    kUninitialized = 0,
    kRegistered,
    kAvailable,
    kSuspended,
    kRestricted,
    kRetiring,
    kRetired
};

}  // namespace ak::tool
