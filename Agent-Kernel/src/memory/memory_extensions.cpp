// ============================================================
// Agent Kernel - MemoryExtensionBoundary (Memory boundary)
// ============================================================
// Implementation of the Memory-owned extension boundary.
// ============================================================

#include <agent_kernel/memory/memory_extensions.hpp>

#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace ak::memory {

MemoryAttachResult MemoryExtensionBoundary::Attach(
    std::shared_ptr<IMemoryExtension> extension) {
    if (extension == nullptr) {
        return {false, "extension is null"};
    }
    if (extension->Domain() != MemoryExtensionDomain::kMemory) {
        return {false,
                "non-Memory extensions cannot attach to the Memory extension boundary"};
    }
    if (Contains(extension->Name())) {
        return {false, "extension with the same name is already attached"};
    }
    Entry entry;
    entry.extension = std::move(extension);
    entry.state = MemoryExtensionState::kAttached;
    entries_.push_back(std::move(entry));
    return {true, "attached"};
}

bool MemoryExtensionBoundary::Detach(std::string_view name) {
    for (auto it = entries_.begin(); it != entries_.end(); ++it) {
        if (it->extension->Name() == name) {
            entries_.erase(it);
            return true;
        }
    }
    return false;
}

bool MemoryExtensionBoundary::Activate(std::string_view name) {
    Entry* entry = Find(name);
    if (entry == nullptr) {
        return false;
    }
    entry->state = MemoryExtensionState::kActive;
    return true;
}

bool MemoryExtensionBoundary::Suspend(std::string_view name) {
    Entry* entry = Find(name);
    if (entry == nullptr) {
        return false;
    }
    entry->state = MemoryExtensionState::kSuspended;
    return true;
}

bool MemoryExtensionBoundary::SetConfiguration(
    std::string_view name, ak::KernelMetadata configuration) {
    Entry* entry = Find(name);
    if (entry == nullptr) {
        return false;
    }
    entry->configuration = std::move(configuration);
    return true;
}

bool MemoryExtensionBoundary::Contains(std::string_view name) const noexcept {
    return Find(name) != nullptr;
}

std::vector<std::string> MemoryExtensionBoundary::Enumerate() const {
    std::vector<std::string> names;
    names.reserve(entries_.size());
    for (const auto& entry : entries_) {
        names.emplace_back(entry.extension->Name());
    }
    return names;
}

MemoryExtensionState MemoryExtensionBoundary::GetState(
    std::string_view name) const noexcept {
    const Entry* entry = Find(name);
    if (entry == nullptr) {
        return MemoryExtensionState::kDetached;
    }
    return entry->state;
}

bool MemoryExtensionBoundary::ValidateIntegrity() const noexcept {
    for (const auto& entry : entries_) {
        if (!entry.extension->SelfCheck()) {
            return false;
        }
    }
    return true;
}

bool MemoryExtensionBoundary::ValidateCompatibility() const noexcept {
    for (const auto& entry : entries_) {
        if (entry.extension->Version().major != SupportedMajorVersion()) {
            return false;
        }
    }
    return true;
}

void MemoryExtensionBoundary::ValidateBoundary(
    ak::DiagnosticSink& sink) const {
    for (const auto& entry : entries_) {
        if (entry.extension->Domain() != MemoryExtensionDomain::kMemory) {
            sink.Add(ak::DiagnosticSeverity::kError, 40,
                     "non-Memory extension attached to the Memory boundary");
        }
        if (!entry.extension->SelfCheck()) {
            sink.Add(ak::DiagnosticSeverity::kError, 41,
                     "extension integrity check failed");
        }
        if (entry.extension->Version().major != SupportedMajorVersion()) {
            sink.Add(ak::DiagnosticSeverity::kError, 42,
                     "extension compatibility check failed");
        }
    }
}

bool MemoryExtensionBoundary::ContainsForeignExtension() const noexcept {
    for (const auto& entry : entries_) {
        if (entry.extension->Domain() != MemoryExtensionDomain::kMemory) {
            return true;
        }
    }
    return false;
}

MemoryExtensionBoundary::Entry* MemoryExtensionBoundary::Find(
    std::string_view name) noexcept {
    for (auto& entry : entries_) {
        if (entry.extension->Name() == name) {
            return &entry;
        }
    }
    return nullptr;
}

const MemoryExtensionBoundary::Entry* MemoryExtensionBoundary::Find(
    std::string_view name) const noexcept {
    for (const auto& entry : entries_) {
        if (entry.extension->Name() == name) {
            return &entry;
        }
    }
    return nullptr;
}

}  // namespace ak::memory