// ============================================================
// Agent Kernel — TaskDependency
// ============================================================
// Lightweight value type representing one dependency
// relationship from the perspective of a Task.
//
// A TaskDependency says: "I, Task[from], depend on
// Task[to] completing before I can be executed."
//
// TaskDependency uses only TaskID — it does NOT store
// Task pointers, references, shared_ptr, or weak_ptr.
// Dependencies are logical relationships, not ownership
// or runtime references.
//
// The execution ordering derived from dependencies belongs
// to WorkflowGraph (AK0013), not to TaskDependency.
// ============================================================

#pragma once

#include <agent_kernel/object_id.hpp>

namespace ak {

// ============================================================
// DependencyKind — classification of the dependency
// ============================================================
enum class DependencyKind : unsigned char {
    // Data dependency: Task depends on upstream's output
    kData = 0,

    // Control dependency: Task depends on upstream's completion
    kControl,

    // Reserved for future:
    // kResource (requires a resource held by upstream)
    // kTiming (requires a time window relative to upstream)
};

// ============================================================
// TaskDependency — value type
// ============================================================
class TaskDependency {
public:
    TaskDependency(TaskID upstreamTask,
                   DependencyKind kind = DependencyKind::kData) noexcept;

    // -- The upstream task that this task depends on --
    [[nodiscard]] TaskID GetUpstreamTaskID() const noexcept;

    // -- The kind of dependency --
    [[nodiscard]] DependencyKind GetKind() const noexcept;

    // -- Comparison --
    auto operator<=>(const TaskDependency&) const = default;

private:
    TaskID upstreamTask_;
    DependencyKind kind_;
};

}  // namespace ak
