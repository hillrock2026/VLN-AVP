// ============================================================
// Agent Kernel - ContextServices (Context boundary)
// ============================================================
// Implementation of the Context Service boundary. All object
// access and mutation passes through this boundary; lifecycle
// and operational-state validity are enforced here.
// ============================================================

#include <agent_kernel/context/context_services.hpp>

#include <memory>
#include <utility>

namespace ak::context {

// ------------------------------------------------------------
// Context Creation Service
// ------------------------------------------------------------

ContextResultValue<ContextObjectId> ContextCreationService::CreateObject(
    ContextObjectId id, std::string category, std::string content,
    ContextMetadata metadata) {
    if (!id.IsValid()) {
        return {ContextResultStatus::kInvalid,
                "invalid Context Object identity", {}};
    }
    if (store_.objects_.Contains(id)) {
        return {ContextResultStatus::kConflict,
                "Context Object identity already registered", {}};
    }
    store_.objects_.Register(
        id, std::make_unique<ContextObject>(id, std::move(category),
                                            std::move(content),
                                            std::move(metadata)));
    return {ContextResultStatus::kSuccess, "Context Object created", id};
}

ContextResult ContextCreationService::InitializeObject(ContextObjectId id) {
    ContextObject* object = store_.objects_.Find(id);
    if (object == nullptr) {
        return {ContextResultStatus::kInvalid, "Context Object not found"};
    }
    // Context-owned lockstep: lifecycle Created -> Initialized and
    // operational Uninitialized -> Ready. Both transitions are
    // deterministic from a newly created Object.
    const ContextResult lifecycle = object->lifecycle_.Initialize();
    if (!lifecycle.IsSuccess()) {
        return lifecycle;
    }
    const ContextResult operational = object->operational_.ToReady();
    if (!operational.IsSuccess()) {
        return {ContextResultStatus::kFailure,
                "Context Object consistency violation during initialization"};
    }
    return {ContextResultStatus::kSuccess, "Context Object initialized"};
}

ContextResult ContextCreationService::ActivateObject(ContextObjectId id) {
    ContextObject* object = store_.objects_.Find(id);
    if (object == nullptr) {
        return {ContextResultStatus::kInvalid, "Context Object not found"};
    }
    // Creation does not imply activation: an explicit activation
    // request is required for participation.
    const ContextResult lifecycle = object->lifecycle_.Activate();
    if (!lifecycle.IsSuccess()) {
        return lifecycle;
    }
    const ContextResult operational = object->operational_.ToActive();
    if (!operational.IsSuccess()) {
        return {ContextResultStatus::kFailure,
                "Context Object consistency violation during activation"};
    }
    return {ContextResultStatus::kSuccess, "Context Object activated"};
}

std::size_t ContextCreationService::ObjectCount() const noexcept {
    return store_.objects_.Count();
}

// ------------------------------------------------------------
// Context Access Service
// ------------------------------------------------------------

ContextResultValue<ContextObjectView> ContextAccessService::InspectObject(
    ContextObjectId id) const {
    const ContextObject* object = store_.objects_.Find(id);
    if (object == nullptr) {
        return {ContextResultStatus::kInvalid, "Context Object not found", {}};
    }
    if (object->GetLifecycleState() == ContextLifecycleState::kReleased ||
        object->GetOperationalState() == ContextOperationalState::kReleased) {
        return {ContextResultStatus::kReleased,
                "Context Object is already released", {}};
    }
    ContextObjectView view;
    view.id = object->GetId();
    view.category = object->GetCategory();
    view.content = object->Content();
    view.metadata = object->GetMetadata();
    view.lifecycle = object->GetLifecycleState();
    view.operational = object->GetOperationalState();
    return {ContextResultStatus::kSuccess, "Context Object inspected",
            std::move(view)};
}

ContextResultValue<std::vector<ContextObjectId>> ContextAccessService::ListObjects()
    const {
    return {ContextResultStatus::kSuccess, "Context Objects enumerated",
            store_.objects_.Enumerate()};
}

std::size_t ContextAccessService::ObjectCount() const noexcept {
    return store_.objects_.Count();
}

// ------------------------------------------------------------
// Context Update Service
// ------------------------------------------------------------

ContextResult ContextUpdateService::BeginUpdate(ContextObjectId id) {
    ContextObject* object = store_.objects_.Find(id);
    if (object == nullptr) {
        return {ContextResultStatus::kInvalid, "Context Object not found"};
    }
    if (object->GetLifecycleState() == ContextLifecycleState::kReleased ||
        object->GetOperationalState() == ContextOperationalState::kReleased) {
        return {ContextResultStatus::kReleased,
                "Context Object is already released"};
    }
    if (object->GetLifecycleState() != ContextLifecycleState::kActive) {
        return {ContextResultStatus::kUnavailable,
                "Context Object is not active and cannot be updated"};
    }
    // Lifecycle Active -> Updated and operational Active ->
    // Updating in lockstep.
    const ContextResult lifecycle = object->lifecycle_.BeginUpdate();
    if (!lifecycle.IsSuccess()) {
        return lifecycle;
    }
    const ContextResult operational = object->operational_.ToUpdating();
    if (!operational.IsSuccess()) {
        return {ContextResultStatus::kFailure,
                "Context Object consistency violation during update"};
    }
    return {ContextResultStatus::kSuccess, "Context Object update began"};
}

ContextResult ContextUpdateService::ApplyUpdate(ContextObjectId id,
                                                std::string content,
                                                ContextMetadata metadata) {
    ContextObject* object = store_.objects_.Find(id);
    if (object == nullptr) {
        return {ContextResultStatus::kInvalid, "Context Object not found"};
    }
    if (object->GetLifecycleState() == ContextLifecycleState::kReleased ||
        object->GetOperationalState() == ContextOperationalState::kReleased) {
        return {ContextResultStatus::kReleased,
                "Context Object is already released"};
    }
    if (object->GetLifecycleState() != ContextLifecycleState::kUpdated ||
        object->GetOperationalState() != ContextOperationalState::kUpdating) {
        return {ContextResultStatus::kInvalid,
                "invalid update: Object is not in the updating state"};
    }
    object->content_ = std::move(content);
    object->metadata_ = std::move(metadata);
    return {ContextResultStatus::kSuccess, "Context Object working state updated"};
}

ContextResult ContextUpdateService::CompleteUpdate(ContextObjectId id) {
    ContextObject* object = store_.objects_.Find(id);
    if (object == nullptr) {
        return {ContextResultStatus::kInvalid, "Context Object not found"};
    }
    // Lifecycle Updated -> Active and operational Updating ->
    // Active in lockstep.
    const ContextResult lifecycle = object->lifecycle_.CompleteUpdate();
    if (!lifecycle.IsSuccess()) {
        return lifecycle;
    }
    const ContextResult operational = object->operational_.ToActiveAfterUpdate();
    if (!operational.IsSuccess()) {
        return {ContextResultStatus::kFailure,
                "Context Object consistency violation while completing update"};
    }
    return {ContextResultStatus::kSuccess, "Context Object update completed"};
}

// ------------------------------------------------------------
// Context Composition Service
// ------------------------------------------------------------

ContextResultValue<ContextRelationshipId>
ContextCompositionService::ComposeRelationship(
    ContextRelationshipId relationship_id, ContextObjectId source,
    ContextObjectId target, std::string kind, ContextMetadata metadata) {
    if (!relationship_id.IsValid()) {
        return {ContextResultStatus::kInvalid,
                "invalid Context Relationship identity", {}};
    }
    if (!source.IsValid() || !target.IsValid()) {
        return {ContextResultStatus::kInvalid,
                "invalid Context Object identity in composition", {}};
    }
    if (source == target) {
        return {ContextResultStatus::kInvalid,
                "invalid composition: an Object cannot relate to itself", {}};
    }
    const ContextObject* source_object = store_.objects_.Find(source);
    if (source_object == nullptr) {
        return {ContextResultStatus::kInvalid,
                "composition source Context Object not found", {}};
    }
    const ContextObject* target_object = store_.objects_.Find(target);
    if (target_object == nullptr) {
        return {ContextResultStatus::kInvalid,
                "composition target Context Object not found", {}};
    }
    if (source_object->GetLifecycleState() == ContextLifecycleState::kReleased ||
        target_object->GetLifecycleState() == ContextLifecycleState::kReleased) {
        return {ContextResultStatus::kReleased,
                "released Context Objects cannot participate in composition",
                {}};
    }
    if (store_.relationships_.Contains(relationship_id)) {
        return {ContextResultStatus::kConflict,
                "Context Relationship identity already registered", {}};
    }
    store_.relationships_.Register(
        relationship_id,
        std::make_unique<ContextRelationship>(relationship_id, source, target,
                                              std::move(kind),
                                              std::move(metadata)));
    return {ContextResultStatus::kSuccess, "Context Relationship composed",
            relationship_id};
}

ContextResultValue<std::vector<ContextRelationship>>
ContextCompositionService::ListRelationshipsOf(ContextObjectId object_id) const {
    if (!object_id.IsValid()) {
        return {ContextResultStatus::kInvalid,
                "invalid Context Object identity", {}};
    }
    if (store_.objects_.Find(object_id) == nullptr) {
        return {ContextResultStatus::kInvalid, "Context Object not found", {}};
    }
    std::vector<ContextRelationship> relationships;
    for (const ContextRelationshipId relationship_id :
         store_.relationships_.Enumerate()) {
        const ContextRelationship* relationship =
            store_.relationships_.Find(relationship_id);
        if (relationship != nullptr &&
            (relationship->GetSourceId() == object_id ||
             relationship->GetTargetId() == object_id)) {
            relationships.push_back(*relationship);
        }
    }
    return {ContextResultStatus::kSuccess,
            "Context Relationships enumerated", std::move(relationships)};
}

std::size_t ContextCompositionService::RelationshipCount() const noexcept {
    return store_.relationships_.Count();
}

// ------------------------------------------------------------
// Context Release Service
// ------------------------------------------------------------

ContextResult ContextReleaseService::ReleaseObject(ContextObjectId id) {
    ContextObject* object = store_.objects_.Find(id);
    if (object == nullptr) {
        return {ContextResultStatus::kInvalid, "Context Object not found"};
    }
    if (object->GetLifecycleState() == ContextLifecycleState::kReleased ||
        object->GetOperationalState() == ContextOperationalState::kReleased) {
        return {ContextResultStatus::kReleased,
                "Context Object is already released"};
    }
    // Lifecycle Active/Updated -> Released and operational
    // Active -> Released. Release is terminal and irreversible.
    if (object->GetLifecycleState() != ContextLifecycleState::kActive &&
        object->GetLifecycleState() != ContextLifecycleState::kUpdated) {
        return {ContextResultStatus::kRejected,
                "invalid lifecycle transition: Object cannot be released"};
    }
    if (object->GetOperationalState() != ContextOperationalState::kActive) {
        return {ContextResultStatus::kRejected,
                "invalid state transition: Object must be Active to be "
                "released"};
    }
    const ContextResult lifecycle = object->lifecycle_.Release();
    if (!lifecycle.IsSuccess()) {
        return lifecycle;
    }
    const ContextResult operational = object->operational_.ToReleased();
    if (!operational.IsSuccess()) {
        return {ContextResultStatus::kFailure,
                "Context Object consistency violation during release"};
    }
    return {ContextResultStatus::kSuccess, "Context Object released"};
}

}  // namespace ak::context
