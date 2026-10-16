// ============================================================
// Agent Kernel - AgentExtensionBoundary (Agent boundary)
// ============================================================
// Implementation of the Agent-specific extension boundary.
// ============================================================

#include <agent_kernel/agent/extension/agent_extension_boundary.hpp>

#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace ak::agent {

AttachResult AgentExtensionBoundary::Attach(
    std::shared_ptr<IAgentExtension> extension) {
    if (extension == nullptr) {
        return {false, "extension is null"};
    }
    if (extension->Domain() != AgentExtensionDomain::kAgentSpecific) {
        return {false,
                "subsystem extensions cannot attach to the Agent-specific extension boundary"};
    }
    if (Contains(extension->Name())) {
        return {false, "extension with the same name is already attached"};
    }
    Entry entry;
    entry.extension = std::move(extension);
    entry.state = AgentExtensionState::kAttached;
    entries_.push_back(std::move(entry));
    return {true, "attached"};
}

bool AgentExtensionBoundary::Detach(std::string_view name) {
    for (auto it = entries_.begin(); it != entries_.end(); ++it) {
        if (it->extension->Name() == name) {
            entries_.erase(it);
            return true;
        }
    }
    return false;
}

bool AgentExtensionBoundary::Activate(std::string_view name) {
    Entry* entry = Find(name);
    if (entry == nullptr) {
        return false;
    }
    entry->state = AgentExtensionState::kActive;
    return true;
}

bool AgentExtensionBoundary::Suspend(std::string_view name) {
    Entry* entry = Find(name);
    if (entry == nullptr) {
        return false;
    }
    entry->state = AgentExtensionState::kSuspended;
    return true;
}

bool AgentExtensionBoundary::SetConfiguration(
    std::string_view name, ak::KernelMetadata configuration) {
    Entry* entry = Find(name);
    if (entry == nullptr) {
        return false;
    }
    entry->configuration = std::move(configuration);
    return true;
}

bool AgentExtensionBoundary::Contains(std::string_view name) const noexcept {
    return Find(name) != nullptr;
}

std::vector<std::string> AgentExtensionBoundary::Enumerate() const {
    std::vector<std::string> names;
    names.reserve(entries_.size());
    for (const auto& entry : entries_) {
        names.emplace_back(entry.extension->Name());
    }
    return names;
}

AgentExtensionState AgentExtensionBoundary::GetState(
    std::string_view name) const noexcept {
    const Entry* entry = Find(name);
    if (entry == nullptr) {
        return AgentExtensionState::kDetached;
    }
    return entry->state;
}

bool AgentExtensionBoundary::ValidateIntegrity() const noexcept {
    for (const auto& entry : entries_) {
        if (!entry.extension->SelfCheck()) {
            return false;
        }
    }
    return true;
}

bool AgentExtensionBoundary::ValidateCompatibility() const noexcept {
    for (const auto& entry : entries_) {
        if (entry.extension->Version().major != SupportedMajorVersion()) {
            return false;
        }
    }
    return true;
}

void AgentExtensionBoundary::ValidateBoundary(
    ak::DiagnosticSink& sink) const {
    for (const auto& entry : entries_) {
        if (entry.extension->Domain() != AgentExtensionDomain::kAgentSpecific) {
            sink.Add(ak::DiagnosticSeverity::kError, 10,
                     "subsystem extension attached to the Agent-specific boundary");
        }
        if (!entry.extension->SelfCheck()) {
            sink.Add(ak::DiagnosticSeverity::kError, 11,
                     "extension integrity check failed");
        }
        if (entry.extension->Version().major != SupportedMajorVersion()) {
            sink.Add(ak::DiagnosticSeverity::kError, 12,
                     "extension compatibility check failed");
        }
    }
}

bool AgentExtensionBoundary::ContainsSubsystemExtension() const noexcept {
    for (const auto& entry : entries_) {
        if (entry.extension->Domain() != AgentExtensionDomain::kAgentSpecific) {
            return true;
        }
    }
    return false;
}

AgentExtensionBoundary::Entry* AgentExtensionBoundary::Find(
    std::string_view name) noexcept {
    for (auto& entry : entries_) {
        if (entry.extension->Name() == name) {
            return &entry;
        }
    }
    return nullptr;
}

const AgentExtensionBoundary::Entry* AgentExtensionBoundary::Find(
    std::string_view name) const noexcept {
    for (const auto& entry : entries_) {
        if (entry.extension->Name() == name) {
            return &entry;
        }
    }
    return nullptr;
}

}  // namespace ak::agent
