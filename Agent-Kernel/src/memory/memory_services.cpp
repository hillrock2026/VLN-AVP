// ============================================================
// Agent Kernel - MemoryServices (Memory boundary)
// ============================================================
// Implementation of the Memory Service boundary. All object
// access and mutation passes through this boundary.
// ============================================================

#include <agent_kernel/memory/memory_services.hpp>

#include <memory>
#include <utility>

namespace ak::memory {

MemoryService::MemoryService(MemoryLifecycle& lifecycle,
                             MemoryOperationalStateMachine& operational,
                             MemoryStore& store, IMemoryProvider* provider) noexcept
    : lifecycle_(lifecycle), operational_(operational), store_(store),
      provider_(provider) {}

MemoryResult MemoryService::CheckAvailability() const noexcept {
    if (lifecycle_.GetState() != MemoryLifecycleState::kActive) {
        return {MemoryResultStatus::kRejected,
                "lifecycle does not permit Memory service operations"};
    }
    if (provider_ == nullptr) {
        return {MemoryResultStatus::kFailure,
                "Memory owns no provider"};
    }
    switch (operational_.GetState()) {
        case MemoryOperationalState::kUnavailable:
            return {MemoryResultStatus::kUnavailable,
                    "Memory operational state is Unavailable"};
        case MemoryOperationalState::kReady:
            return {MemoryResultStatus::kUnavailable,
                    "Memory operational state is Ready (preparation only)"};
        case MemoryOperationalState::kAvailable:
        case MemoryOperationalState::kBusy:
        case MemoryOperationalState::kDegraded:
            return {MemoryResultStatus::kSuccess, ""};
    }
    return {MemoryResultStatus::kFailure,
            "Memory operational state is not normative"};
}

MemoryResult MemoryService::HandleProviderFailure(
    const ProviderResult& failure) noexcept {
    // Memory-owned consequence: when fully available, a provider
    // failure contributes to the normative Available -> Degraded
    // transition. The provider never mutates this state itself.
    if (operational_.GetState() == MemoryOperationalState::kAvailable) {
        (void)operational_.ToDegraded();
    }
    const char* message =
        (failure.message != nullptr && failure.message[0] != '\0')
            ? failure.message
            : "provider failure";
    return {MemoryResultStatus::kFailure, message};
}

MemoryResultValue<MemoryObject> MemoryService::LoadObjectFromProvider(
    MemoryObjectId object_id) {
    std::string content;
    MemoryMetadata metadata;
    const ProviderResult loaded =
        provider_->LoadObject(object_id, content, metadata);
    if (loaded.status == ProviderStatus::kNotFound) {
        return {MemoryResultStatus::kInvalid,
                "object does not exist", {}};
    }
    if (!loaded.IsSuccess()) {
        const MemoryResult failure = HandleProviderFailure(loaded);
        return {failure.status, failure.message, {}};
    }
    // Invariant: every object retrievable from the provider must
    // be registered in the Memory-owned store.
    if (store_.objects_.Find(object_id) == nullptr) {
        return {MemoryResultStatus::kFailure,
                "Memory object consistency violation", {}};
    }
    return {MemoryResultStatus::kSuccess, "retrieved",
            MemoryObject(object_id, std::move(content), std::move(metadata))};
}

MemoryResultValue<MemoryDomainId> MemoryService::CreateDomain(
    MemoryDomainId id, std::string name, MemoryMetadata metadata) {
    const MemoryResult gate = CheckAvailability();
    if (!gate.IsSuccess()) {
        return {gate.status, gate.message, {}};
    }
    if (!id.IsValid()) {
        return {MemoryResultStatus::kInvalid, "invalid Domain identity", {}};
    }
    if (store_.domains_.Contains(id)) {
        return {MemoryResultStatus::kConflict,
                "Domain identity already registered", {}};
    }
    auto domain = std::make_unique<MemoryDomain>(id, std::move(name),
                                                 std::move(metadata));
    store_.domains_.Register(id, std::move(domain));
    return {MemoryResultStatus::kSuccess, "Domain created", id};
}

MemoryResultValue<MemoryDomain> MemoryService::FindDomain(MemoryDomainId id) {
    const MemoryResult gate = CheckAvailability();
    if (!gate.IsSuccess()) {
        return {gate.status, gate.message, {}};
    }
    const MemoryDomain* domain = store_.domains_.Find(id);
    if (domain == nullptr) {
        return {MemoryResultStatus::kInvalid, "Domain does not exist", {}};
    }
    return {MemoryResultStatus::kSuccess, "Domain found", *domain};
}

std::size_t MemoryService::DomainCount() const noexcept {
    return store_.domains_.Count();
}

MemoryResultValue<MemoryEntryId> MemoryService::Retain(
    MemoryEntryId entry_id, MemoryDomainId domain_id, MemoryObject object) {
    const MemoryResult gate = CheckAvailability();
    if (!gate.IsSuccess()) {
        return {gate.status, gate.message, {}};
    }
    if (!entry_id.IsValid() || !domain_id.IsValid() ||
        !object.GetId().IsValid()) {
        return {MemoryResultStatus::kInvalid,
                "invalid Entry, Domain, or Object identity", {}};
    }
    if (store_.entries_.Contains(entry_id)) {
        return {MemoryResultStatus::kConflict,
                "Entry identity already registered", {}};
    }
    if (store_.objects_.Contains(object.GetId())) {
        return {MemoryResultStatus::kConflict,
                "Object identity already registered", {}};
    }
    if (store_.domains_.Find(domain_id) == nullptr) {
        return {MemoryResultStatus::kInvalid, "Domain does not exist", {}};
    }

    // Provider-mediated storage happens BEFORE any Memory-owned
    // registration: a provider failure leaves no partial entry
    // and no dangling reference (failure atomicity).
    const ProviderResult stored = provider_->StoreObject(
        object.GetId(), object.Content(), object.GetMetadata());
    if (!stored.IsSuccess()) {
        const MemoryResult failure = HandleProviderFailure(stored);
        return {failure.status, failure.message, {}};
    }

    auto entry = std::make_unique<MemoryEntry>(
        entry_id, domain_id, object.GetId(), object.GetMetadata());
    store_.objects_.Register(object.GetId(),
                             std::make_unique<MemoryObject>(std::move(object)));
    store_.entries_.Register(entry_id, std::move(entry));
    return {MemoryResultStatus::kSuccess, "retained", entry_id};
}

MemoryResultValue<MemoryObject> MemoryService::Retrieve(MemoryEntryId entry_id) {
    const MemoryResult gate = CheckAvailability();
    if (!gate.IsSuccess()) {
        return {gate.status, gate.message, {}};
    }
    const MemoryEntry* entry = store_.entries_.Find(entry_id);
    if (entry == nullptr) {
        return {MemoryResultStatus::kInvalid, "Entry does not exist", {}};
    }
    return LoadObjectFromProvider(entry->GetObjectId());
}

MemoryResultValue<MemoryObject> MemoryService::LookupObject(
    MemoryObjectId object_id) {
    const MemoryResult gate = CheckAvailability();
    if (!gate.IsSuccess()) {
        return {gate.status, gate.message, {}};
    }
    if (!object_id.IsValid()) {
        return {MemoryResultStatus::kInvalid, "invalid Object identity", {}};
    }
    return LoadObjectFromProvider(object_id);
}

MemoryResultValue<MemoryReference> MemoryService::LookupReference(
    MemoryObjectId object_id) {
    const MemoryResult gate = CheckAvailability();
    if (!gate.IsSuccess()) {
        return {gate.status, gate.message, {}};
    }
    if (!object_id.IsValid()) {
        return {MemoryResultStatus::kInvalid, "invalid Object identity", {}};
    }
    if (store_.objects_.Find(object_id) == nullptr) {
        return {MemoryResultStatus::kInvalid, "Object does not exist", {}};
    }
    // A reference carries architectural identity only: the
    // Domain of the first Entry that references the Object.
    for (const MemoryEntryId entry_id : store_.entries_.Enumerate()) {
        const MemoryEntry* entry = store_.entries_.Find(entry_id);
        if (entry != nullptr && entry->GetObjectId() == object_id) {
            return {MemoryResultStatus::kSuccess, "reference resolved",
                    MemoryReference(entry->GetDomainId(), object_id)};
        }
    }
    return {MemoryResultStatus::kFailure,
            "Object exists without a referencing Entry", {}};
}

MemoryResultValue<MemoryEntry> MemoryService::FindEntry(MemoryEntryId entry_id) {
    const MemoryResult gate = CheckAvailability();
    if (!gate.IsSuccess()) {
        return {gate.status, gate.message, {}};
    }
    const MemoryEntry* entry = store_.entries_.Find(entry_id);
    if (entry == nullptr) {
        return {MemoryResultStatus::kInvalid, "Entry does not exist", {}};
    }
    return {MemoryResultStatus::kSuccess, "Entry found", *entry};
}

MemoryResultValue<std::vector<MemoryEntryId>> MemoryService::ListEntries(
    MemoryDomainId domain_id) {
    const MemoryResult gate = CheckAvailability();
    if (!gate.IsSuccess()) {
        return {gate.status, gate.message, {}};
    }
    if (store_.domains_.Find(domain_id) == nullptr) {
        return {MemoryResultStatus::kInvalid, "Domain does not exist", {}};
    }
    std::vector<MemoryEntryId> entries;
    for (const MemoryEntryId entry_id : store_.entries_.Enumerate()) {
        const MemoryEntry* entry = store_.entries_.Find(entry_id);
        if (entry != nullptr && entry->GetDomainId() == domain_id) {
            entries.push_back(entry_id);
        }
    }
    return {MemoryResultStatus::kSuccess, "entries enumerated", std::move(entries)};
}

std::size_t MemoryService::EntryCount() const noexcept {
    return store_.entries_.Count();
}

MemoryResultValue<MemoryMetadata> MemoryService::GetEntryMetadata(
    MemoryEntryId entry_id) {
    const MemoryResult gate = CheckAvailability();
    if (!gate.IsSuccess()) {
        return {gate.status, gate.message, {}};
    }
    const MemoryEntry* entry = store_.entries_.Find(entry_id);
    if (entry == nullptr) {
        return {MemoryResultStatus::kInvalid, "Entry does not exist", {}};
    }
    return {MemoryResultStatus::kSuccess, "metadata read", entry->GetMetadata()};
}

MemoryResult MemoryService::SetEntryMetadata(MemoryEntryId entry_id,
                                             MemoryMetadata metadata) {
    const MemoryResult gate = CheckAvailability();
    if (!gate.IsSuccess()) {
        return gate;
    }
    MemoryEntry* entry = store_.entries_.Find(entry_id);
    if (entry == nullptr) {
        return {MemoryResultStatus::kInvalid, "Entry does not exist"};
    }
    entry->metadata_ = std::move(metadata);
    return {MemoryResultStatus::kSuccess, "metadata updated"};
}

MemoryResult MemoryService::RemoveEntry(MemoryEntryId entry_id) {
    const MemoryResult gate = CheckAvailability();
    if (!gate.IsSuccess()) {
        return gate;
    }
    if (store_.entries_.Find(entry_id) == nullptr) {
        return {MemoryResultStatus::kInvalid, "Entry does not exist"};
    }
    // Organization change only: the referenced Object remains
    // retained; no dangling reference is created because
    // references are resolved on demand from the store.
    store_.entries_.Unregister(entry_id);
    return {MemoryResultStatus::kSuccess, "Entry removed"};
}

void MemoryService::BindProvider(IMemoryProvider& provider) noexcept {
    provider_ = &provider;
}

}  // namespace ak::memory