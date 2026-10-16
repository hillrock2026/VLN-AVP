// ============================================================
// Agent Kernel - ExecutorConfiguration
// ============================================================
// Immutable configuration for an Executor instance.
//
// AK0022 Chapter 8 - Executor API Contract
// ============================================================

#pragma once

#include <cstdint>
#include <memory>
#include <string>

namespace ak {

// ============================================================
// ExecutorConfiguration
// ============================================================
struct ExecutorConfiguration {
    // Maximum number of concurrent executions
    std::uint32_t maxConcurrency = 1;

    // Name for logging/diagnostics
    std::string name = "default";

    // Reserved for future:
    // std::chrono::milliseconds defaultTimeout;
    // bool enableRetry = false;
    // std::uint32_t maxRetryCount = 0;
};

}  // namespace ak
