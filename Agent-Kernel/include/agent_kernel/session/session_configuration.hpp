// ============================================================
// Agent Kernel — SessionConfiguration
// ============================================================
// Immutable value object containing Session construction
// parameters.
//
// SessionConfiguration is a value type. It is set once
// during Session construction (via SessionBuilder) and
// remains read-only for the lifetime of the Session.
//
// It contains ONLY structural configuration:
// - Identity hints (name, version)
// - Capacity limits (max workflows)
// - Extension properties (future)
//
// It does NOT contain runtime configuration:
// - Thread count (belongs to Runtime)
// - Scheduling policy (belongs to Scheduler)
// - Retry policy (belongs to Executor)
// - Execution options (belongs to Runtime)
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <chrono>
#include <optional>

namespace ak {

// ============================================================
// SessionConfiguration
// ============================================================
struct SessionConfiguration {
    // Human-readable session name (for display/logging)
    std::string name;

    // Schema version for future configuration evolution
    std::uint32_t version = 1;

    // Maximum number of concurrent Workflows
    // 0 means unlimited (default).
    std::uint32_t maxWorkflows = 0;

    // Optional session timeout (future: for idle timeout)
    // std::optional<std::chrono::milliseconds> idleTimeout;

    // Extension properties (future: key-value extension bag)
    // std::unordered_map<std::string, std::string> properties;
};

}  // namespace ak
