// ============================================================
// Agent Kernel - MemoryServices (Memory boundary)
// ============================================================
// Memory Service boundary: the only external object-access
// boundary of Memory.
//
// P1-IS003 scope (Chapter 10 - Service Architecture, Chapter
// 16.1):
// - External consumers interact with Memory Objects, Domains,
//   Entries, References, and Metadata through Memory Services.
// - Services enforce lifecycle and operational-state
//   availability; they reject operations while lifecycle is
//   not Active or the operational state is Unavailable/Ready.
// - Provider failures are mapped by Memory to Memory-owned
//   results and Memory-owned operational transitions.
//
// NON-responsibilities:
// - Services do not expose provider internals or storage
//   identifiers.
// - Services do not plan, modify Context working state, invoke
//   Tool, coordinate peer subsystems, or execute Runtime
//   behavior.
// ============================================================

#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include <agent_kernel/memory/memory_identity.hpp>
#include <agent_kernel/memory/memory_lifecycle.hpp>
#include <agent_kernel/memory/memory_objects.hpp>
#include <agent_kernel/memory/memory_operational_state.hpp>
#include <agent_kernel/memory/memory_provider.hpp>
#include <agent_kernel/memory/memory_result.hpp>
#include <agent_kernel/memory/memory_state.hpp>
#include <agent_kernel/memory/memory_store.hpp>

namespace ak::memory {

class MemoryService {
public:
    MemoryService(MemoryLifecycle& lifecycle, MemoryOperationalStateMachine& operational,
                  MemoryStore& store, IMemoryProvider* provider) noexcept;

    // -- Domain operations --
    [[nodiscard]] MemoryResultValue<MemoryDomainId> CreateDomain(
        MemoryDomainId id, std::string name, MemoryMetadata metadata);
    [[nodiscard]] MemoryResultValue<MemoryDomain> FindDomain(MemoryDomainId id);
    [[nodiscard]] std::size_t DomainCount() const noexcept;

    // -- Retention --
    // Retains a Memory Object under an Entry in the given
    // Domain. The object is stored provider-mediated before any
    // Memory-owned registration occurs (failure atomicity).
    [[nodiscard]] MemoryResultValue<MemoryEntryId> Retain(
        MemoryEntryId entry_id, MemoryDomainId domain_id, MemoryObject object);

    // -- Retrieval --
    [[nodiscard]] MemoryResultValue<MemoryObject> Retrieve(MemoryEntryId entry_id);
    [[nodiscard]] MemoryResultValue<MemoryObject> LookupObject(MemoryObjectId object_id);

    // -- References --
    [[nodiscard]] MemoryResultValue<MemoryReference> LookupReference(
        MemoryObjectId object_id);

    // -- Entry organization --
    [[nodiscard]] MemoryResultValue<MemoryEntry> FindEntry(MemoryEntryId entry_id);
    [[nodiscard]] MemoryResultValue<std::vector<MemoryEntryId>> ListEntries(
        MemoryDomainId domain_id);
    [[nodiscard]] std::size_t EntryCount() const noexcept;

    // -- Metadata handling --
    [[nodiscard]] MemoryResultValue<MemoryMetadata> GetEntryMetadata(
        MemoryEntryId entry_id);
    [[nodiscard]] MemoryResult SetEntryMetadata(MemoryEntryId entry_id,
                                                MemoryMetadata metadata);

    // -- Removal --
    // Removes an Entry (organization change only). The
    // referenced Object remains retained and retrievable.
    [[nodiscard]] MemoryResult RemoveEntry(MemoryEntryId entry_id);

private:
    // Lifecycle/operational availability gate.
    [[nodiscard]] MemoryResult CheckAvailability() const noexcept;

    // Maps a provider failure to a Memory-owned result and a
    // Memory-owned operational consequence (Available ->
    // Degraded when fully available).
    [[nodiscard]] MemoryResult HandleProviderFailure(
        const ProviderResult& failure) noexcept;

    [[nodiscard]] MemoryResultValue<MemoryObject> LoadObjectFromProvider(
        MemoryObjectId object_id);

    // Re-wires the provider reference (Memory-owned operation;
    // used when Memory replaces its provider).
    void BindProvider(IMemoryProvider& provider) noexcept;

    MemoryLifecycle& lifecycle_;
    MemoryOperationalStateMachine& operational_;
    MemoryStore& store_;
    IMemoryProvider* provider_ = nullptr;

    friend class Memory;
};

}  // namespace ak::memory