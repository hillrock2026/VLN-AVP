#pragma once

// ============================================================
// P0R0001 — Runtime Configuration
// ============================================================
// Immutable value object containing Runtime construction
// parameters.
//
// RuntimeConfiguration is a value type. It is set once
// during Runtime construction and remains read-only for
// the lifetime of the Runtime.
//
// P0R0001 scope:
// - Basic configuration structure only
// - No scheduling, execution, or event configuration
// - Extended in P0R0002+
// ============================================================

#include <cstdint>
#include <string>

namespace ak::runtime {

// ============================================================
// RuntimeConfiguration
// ============================================================
struct RuntimeConfiguration {
    // Human-readable Runtime instance name (for logging/diagnostics)
    std::string instanceName = "default";

    // Schema version for future configuration evolution
    std::uint32_t version = 1;

    // Enable internal validation checks
    bool enableValidation = true;

    // Enable diagnostic logging
    bool enableDiagnostics = false;
};

}  // namespace ak::runtime