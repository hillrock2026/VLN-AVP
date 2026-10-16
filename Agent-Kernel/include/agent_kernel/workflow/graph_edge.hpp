// ============================================================
// Agent Kernel — GraphEdge
// ============================================================
// A GraphEdge represents one dependency relationship between
// two Tasks in the Workflow topology.
//
// It contains only:
//   - Source TaskID (the dependent task)
//   - Target TaskID (the task that must complete first)
//   - Dependency type
//
// It does NOT contain:
//   - Runtime data (no execution state, no timestamps)
//   - Task pointers or references
//
// The edge is directional: from -> to means
// "Task[from] depends on Task[to]".
// ============================================================

#pragma once

#include <cstdint>

#include <agent_kernel/object_id.hpp>

namespace ak {

// ============================================================
// DependencyType — classification of the dependency
// ============================================================
enum class DependencyType : std::uint8_t {
    // Task[from] requires Task[to] to complete successfully
    kDataDependency = 0,

    // Task[from] requires Task[to] to complete (any outcome)
    kControlDependency,

    // Reserved for future types:
    // kResourceDependency,
    // kTimingDependency,
};

// ============================================================
// GraphEdge — topology edge
// ============================================================
class GraphEdge {
public:
    GraphEdge(TaskID from, TaskID to,
              DependencyType type = DependencyType::kDataDependency) noexcept;

    // -- Identity --
    [[nodiscard]] TaskID GetFrom() const noexcept;
    [[nodiscard]] TaskID GetTo() const noexcept;

    // -- Type --
    [[nodiscard]] DependencyType GetType() const noexcept;

    // -- Comparison --
    auto operator<=>(const GraphEdge&) const = default;

private:
    TaskID from_;
    TaskID to_;
    DependencyType type_;
};

}  // namespace ak
