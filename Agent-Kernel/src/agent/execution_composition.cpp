// ============================================================
// Agent Kernel - ExecutionComposition (Agent boundary)
// ============================================================
// Implementation of the Agent-owned execution-composition
// representation. Validation is structural only: no Runtime
// action is performed by this component.
// ============================================================

#include <agent_kernel/agent/execution/execution_composition.hpp>

#include <utility>
#include <vector>

namespace ak::agent {

std::uint64_t ExecutionComposition::AddStep(CompositionStep step) {
    if (step.id == 0) {
        step.id = next_step_id_++;
    } else if (HasStep(step.id)) {
        return 0;
    } else if (step.id >= next_step_id_) {
        next_step_id_ = step.id + 1;
    }
    steps_.push_back(std::move(step));
    return steps_.back().id;
}

bool ExecutionComposition::AddDependency(std::uint64_t step,
                                         std::uint64_t depends_on) noexcept {
    if (step == depends_on) {
        return false;
    }
    CompositionStep* target = nullptr;
    for (auto& candidate : steps_) {
        if (candidate.id == step) {
            target = &candidate;
            break;
        }
    }
    if (target == nullptr) {
        return false;
    }
    for (const auto& existing : target->dependencies) {
        if (existing == depends_on) {
            return false;
        }
    }
    for (const auto& candidate : steps_) {
        if (candidate.id == depends_on) {
            target->dependencies.push_back(depends_on);
            return true;
        }
    }
    return false;
}

bool ExecutionComposition::SetConstraint(std::uint64_t step,
                                         std::string constraint) {
    for (auto& candidate : steps_) {
        if (candidate.id == step) {
            candidate.constraints.push_back(std::move(constraint));
            return true;
        }
    }
    return false;
}

bool ExecutionComposition::HasStep(std::uint64_t id) const noexcept {
    for (const auto& step : steps_) {
        if (step.id == id) {
            return true;
        }
    }
    return false;
}

bool ExecutionComposition::Validate() const {
    // Every referenced dependency must name an existing step.
    for (const auto& step : steps_) {
        for (const auto& dependency : step.dependencies) {
            if (!HasStep(dependency)) {
                return false;
            }
        }
    }

    // Cycle detection (iterative DFS over the dependency graph).
    std::vector<std::uint8_t> color(steps_.size(), 0);
    const auto index_of = [this](std::uint64_t id) -> std::size_t {
        for (std::size_t i = 0; i < steps_.size(); ++i) {
            if (steps_[i].id == id) {
                return i;
            }
        }
        return steps_.size();
    };

    const auto has_cycle_from = [&](std::size_t start) -> bool {
        struct Frame {
            std::size_t index;
            std::size_t next_dependency;
        };
        std::vector<Frame> stack;
        stack.push_back({start, 0});
        color[start] = 1;
        while (!stack.empty()) {
            Frame& top = stack.back();
            if (top.next_dependency >= steps_[top.index].dependencies.size()) {
                color[top.index] = 2;
                stack.pop_back();
                continue;
            }
            const std::size_t next =
                index_of(steps_[top.index].dependencies[top.next_dependency]);
            ++top.next_dependency;
            if (next == steps_.size()) {
                return false;  // unknown dependency (already rejected above)
            }
            if (color[next] == 1) {
                return true;  // back edge -> cycle
            }
            if (color[next] == 0) {
                color[next] = 1;
                stack.push_back({next, 0});
            }
        }
        return false;
    };

    for (std::size_t i = 0; i < steps_.size(); ++i) {
        if (color[i] == 0 && has_cycle_from(i)) {
            return false;
        }
    }
    return true;
}

}  // namespace ak::agent
