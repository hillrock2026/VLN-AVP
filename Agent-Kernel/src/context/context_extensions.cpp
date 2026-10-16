// ============================================================
// Agent Kernel - ContextExtensionBoundary (Context boundary)
// ============================================================
// Implementation of the Context-owned extension boundary.
// ============================================================

#include <agent_kernel/context/context_extensions.hpp>

#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace ak::context {

ContextAttachResult ContextExtensionBoundary::Attach(
    std::shared_ptr<IContextExtension> extension) {
    if (extension == nullptr) {
        return {false, "extension is null"};
    }
    if (extension->Domain() != ContextExtensionDomain::kContext) {
        return {false,
                "non-Context extensions cannot attach to the Context extension "
                "boundary"};
    }
    if (Contains(extension->Name())) {
        return {false, "extension with the same name is already attached"};
    }
    Entry entry;
    entry.extension = std::move(extension);
    entry.state = ContextExtensionState::kAttached;
    entries_.push_back(std::move(entry));
    return {true, "attached"};
}

bool ContextExtensionBoundary::Detach(std::string_view name) {
    for (auto it = entries_.begin(); it != entries_.end(); ++it) {
        if (it->extension->Name() == name) {
            entries_.erase(it);
            return true;
        }
    }
    return false;
}

bool ContextExtensionBoundary::Activate(std::string_view name) {
    Entry* entry = Find(name);
    if (entry == nullptr) {
        return false;
    }
    entry->state = ContextExtensionState::kActive;
    return true;
}

bool ContextExtensionBoundary::Suspend(std::string_view name) {
    Entry* entry = Find(name);
    if (entry == nullptr) {
        return false;
    }
    entry->state = ContextExtensionState::kSuspended;
    return true;
}

bool ContextExtensionBoundary::SetConfiguration(
    std::string_view name, ak::KernelMetadata configuration) {
    Entry* entry = Find(name);
    if (entry == nullptr) {
        return false;
    }
    entry->configuration = std::move(configuration);
    return true;
}

bool ContextExtensionBoundary::Contains(std::string_view name) const noexcept {
    return Find(name) != nullptr;
}

std::vector<std::string> ContextExtensionBoundary::Enumerate() const {
    std::vector<std::string> names;
    names.reserve(entries_.size());
    for (const auto& entry : entries_) {
        names.emplace_back(entry.extension->Name());
    }
    return names;
}

ContextExtensionState ContextExtensionBoundary::GetState(
    std::string_view name) const noexcept {
    const Entry* entry = Find(name);
    if (entry == nullptr) {
        return ContextExtensionState::kDetached;
    }
    return entry->state;
}

bool ContextExtensionBoundary::ValidateIntegrity() const noexcept {
    for (const auto& entry : entries_) {
        if (!entry.extension->SelfCheck()) {
            return false;
        }
    }
    return true;
}

bool ContextExtensionBoundary::ValidateCompatibility() const noexcept {
    for (const auto& entry : entries_) {
        if (entry.extension->Version().major != SupportedMajorVersion()) {
            return false;
        }
    }
    return true;
}

void ContextExtensionBoundary::ValidateBoundary(
    ak::DiagnosticSink& sink) const {
    for (const auto& entry : entries_) {
        if (entry.extension->Domain() != ContextExtensionDomain::kContext) {
            sink.Add(ak::DiagnosticSeverity::kError, 50,
                     "non-Context extension attached to the Context boundary");
        }
        if (!entry.extension->SelfCheck()) {
            sink.Add(ak::DiagnosticSeverity::kError, 51,
                     "extension integrity check failed");
        }
        if (entry.extension->Version().major != SupportedMajorVersion()) {
            sink.Add(ak::DiagnosticSeverity::kError, 52,
                     "extension compatibility check failed");
        }
    }
}

bool ContextExtensionBoundary::ContainsForeignExtension() const noexcept {
    for (const auto& entry : entries_) {
        if (entry.extension->Domain() != ContextExtensionDomain::kContext) {
            return true;
        }
    }
    return false;
}

ContextExtensionBoundary::Entry* ContextExtensionBoundary::Find(
    std::string_view name) noexcept {
    for (auto& entry : entries_) {
        if (entry.extension->Name() == name) {
            return &entry;
        }
    }
    return nullptr;
}

const ContextExtensionBoundary::Entry* ContextExtensionBoundary::Find(
    std::string_view name) const noexcept {
    for (const auto& entry : entries_) {
        if (entry.extension->Name() == name) {
            return &entry;
        }
    }
    return nullptr;
}

}  // namespace ak::context
