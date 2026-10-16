// ============================================================
// Agent Kernel - MemoryObjects (Memory boundary)
// ============================================================
// Implementation of the Memory-owned object model values.
// ============================================================

#include <agent_kernel/memory/memory_objects.hpp>

namespace ak::memory {

bool MemoryMetadata::operator==(const MemoryMetadata& other) const noexcept {
    return core.name == other.core.name &&
           core.label == other.core.label &&
           core.description == other.core.description &&
           core.tags == other.core.tags &&
           version == other.version &&
           classification == other.classification &&
           retention_policy == other.retention_policy &&
           annotations == other.annotations;
}

}  // namespace ak::memory