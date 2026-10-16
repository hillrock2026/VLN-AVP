// ============================================================
// Agent Kernel - MemoryStore (Memory boundary)
// ============================================================
// Memory-owned collections of Domains, Objects, and Entries.
//
// P1-IS003 scope (Chapter 7, Chapter 16.3 - Encapsulation):
// - All collections are private to the Memory implementation
//     boundary and are mutated only through the Memory Service
//     boundary.
// - Containment is mechanical (Foundation OwnerScopedRegistry);
//     it does not transfer architectural ownership to the
//     Foundation.
//
// NON-responsibilities:
// - MemoryStore is not a Runtime repository and not a global
//   registry.
// - It is not a service locator or capability resolver.
// ============================================================

#pragma once

#include <agent_kernel/foundation/kernel_registry.hpp>
#include <agent_kernel/memory/memory_objects.hpp>

namespace ak::memory {

class MemoryService;

class MemoryStore {
public:
    MemoryStore() = default;

private:
    ak::OwnerScopedRegistry<MemoryDomainId, MemoryDomain> domains_;
    ak::OwnerScopedRegistry<MemoryObjectId, MemoryObject> objects_;
    ak::OwnerScopedRegistry<MemoryEntryId, MemoryEntry> entries_;

    friend class MemoryService;
};

}  // namespace ak::memory