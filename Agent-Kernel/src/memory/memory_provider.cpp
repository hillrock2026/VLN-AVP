// ============================================================
// Agent Kernel - MemoryProvider (Memory boundary)
// ============================================================
// Implementation of the minimal in-process Memory Provider.
// The provider stores a provider-mediated representation of
// Memory Objects keyed by architectural object identity only.
// It holds no Memory reference, owns no lifecycle/state, and
// cannot coordinate peers or access Runtime.
// ============================================================

#include <agent_kernel/memory/memory_provider.hpp>

#include <string>
#include <string_view>
#include <utility>

namespace ak::memory {

ProviderResult InProcessMemoryProvider::StoreObject(
    MemoryObjectId id, std::string_view content,
    const MemoryMetadata& metadata) {
    if (!id.IsValid()) {
        return {ProviderStatus::kFailure, "invalid object identity"};
    }
    StoredObject stored;
    stored.content.assign(content);
    stored.metadata = metadata;
    objects_[id] = std::move(stored);
    return {ProviderStatus::kSuccess, "stored"};
}

ProviderResult InProcessMemoryProvider::LoadObject(
    MemoryObjectId id, std::string& out_content,
    MemoryMetadata& out_metadata) {
    const auto it = objects_.find(id);
    if (it == objects_.end()) {
        return {ProviderStatus::kNotFound, "object not present in provider"};
    }
    out_content = it->second.content;
    out_metadata = it->second.metadata;
    return {ProviderStatus::kSuccess, "loaded"};
}

ProviderResult InProcessMemoryProvider::RemoveObject(MemoryObjectId id) {
    const auto removed = objects_.erase(id);
    if (removed == 0) {
        return {ProviderStatus::kNotFound, "object not present in provider"};
    }
    return {ProviderStatus::kSuccess, "removed"};
}

}  // namespace ak::memory