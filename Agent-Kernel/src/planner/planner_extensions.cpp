// ============================================================
// Agent Kernel - PlannerExtensions (Planner boundary)
// ============================================================
// Implementation of the Planner-owned extension boundary.
// ============================================================

#include <agent_kernel/planner/planner_extensions.hpp>

#include <algorithm>
#include <utility>

namespace ak::planner {

PlannerAttachResult PlannerExtensionBoundary::Attach(
    std::shared_ptr<IPlannerExtension> extension) {
    if (!extension) {
        return {false, "extension is null"};
    }
    if (extension->Domain() != PlannerExtensionDomain::kPlanner) {
        return {false, "foreign extension domain rejected"};
    }
    if (extension->MajorVersion() != SupportedMajorVersion()) {
        return {false, "unsupported extension major version"};
    }
    if (!extension->SelfCheck()) {
        return {false, "extension self-check failed"};
    }
    const std::string name(extension->Name());
    if (Contains(name)) {
        return {false, "extension name already attached"};
    }
    entries_.push_back(Entry{std::move(extension)});
    return {true, "extension attached"};
}

bool PlannerExtensionBoundary::Detach(std::string_view name) {
    const auto it = std::find_if(
        entries_.begin(), entries_.end(),
        [&](const Entry& entry) { return entry.extension->Name() == name; });
    if (it == entries_.end()) {
        return false;
    }
    entries_.erase(it);
    return true;
}

std::size_t PlannerExtensionBoundary::Count() const noexcept {
    return entries_.size();
}

bool PlannerExtensionBoundary::Contains(std::string_view name) const noexcept {
    for (const auto& entry : entries_) {
        if (entry.extension->Name() == name) {
            return true;
        }
    }
    return false;
}

std::vector<std::string> PlannerExtensionBoundary::Enumerate() const {
    std::vector<std::string> names;
    names.reserve(entries_.size());
    for (const auto& entry : entries_) {
        names.emplace_back(entry.extension->Name());
    }
    return names;
}

bool PlannerExtensionBoundary::ValidateIntegrity() const noexcept {
    for (const auto& entry : entries_) {
        if (!entry.extension) {
            return false;
        }
        if (entry.extension->Domain() != PlannerExtensionDomain::kPlanner) {
            return false;
        }
        if (entry.extension->MajorVersion() != SupportedMajorVersion()) {
            return false;
        }
        if (!entry.extension->SelfCheck()) {
            return false;
        }
    }
    return true;
}

bool PlannerExtensionBoundary::ContainsForeignExtension() const noexcept {
    for (const auto& entry : entries_) {
        if (entry.extension == nullptr ||
            entry.extension->Domain() != PlannerExtensionDomain::kPlanner) {
            return true;
        }
    }
    return false;
}

}  // namespace ak::planner
