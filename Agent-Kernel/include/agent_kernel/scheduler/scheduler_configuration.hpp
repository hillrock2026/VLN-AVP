// ============================================================
// Agent Kernel - SchedulerConfiguration
// ============================================================
// Immutable configuration for a Scheduler instance.
//
// AK0021 Chapter 4 - Scheduler Data Model
// ============================================================

#pragma once

#include <cstdint>
#include <memory>
#include <string>

#include <agent_kernel/scheduler/scheduling_policy.hpp>

namespace ak {

// ============================================================
// SchedulerConfiguration
// ============================================================
struct SchedulerConfiguration {
    // Maximum number of concurrently running tasks
    std::uint32_t maxConcurrency = 1;

    // Name for logging/diagnostics
    std::string name = "default";

    // Scheduling policy implementation
    std::shared_ptr<ISchedulingPolicy> policy;

    // Reserved for future:
    // bool enablePreemption = false;
};

}  // namespace ak
