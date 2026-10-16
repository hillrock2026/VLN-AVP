// ============================================================
// Agent Kernel - ISchedulingPolicy
// ============================================================
// Replaceable scheduling policy abstraction.
//
// AK0021 Chapter 9 - Scheduling Policies
// ============================================================

#pragma once

#include <memory>
#include <optional>
#include <vector>

#include <agent_kernel/object_id.hpp>
#include <agent_kernel/scheduler/i_scheduler.hpp>

namespace ak {

// ============================================================
// ISchedulingPolicy
// ============================================================
class ISchedulingPolicy {
public:
    virtual ~ISchedulingPolicy() noexcept = default;

    [[nodiscard]] virtual std::optional<SchedulingItem> Select(
        const std::vector<SchedulingItem>& runnableTasks) = 0;
};

}  // namespace ak
