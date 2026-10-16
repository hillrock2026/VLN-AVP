// ============================================================
// Agent Kernel - ContextObjects (Context boundary)
// ============================================================
// Implementation of the Context-owned object model values.
// ============================================================

#include <agent_kernel/context/context_objects.hpp>

#include <utility>

namespace ak::context {

ContextObject::ContextObject(ContextObjectId id, std::string category,
                             std::string content, ContextMetadata metadata)
    : id_(id),
      category_(std::move(category)),
      content_(std::move(content)),
      metadata_(std::move(metadata)) {}

ContextRelationship::ContextRelationship(ContextRelationshipId id,
                                         ContextObjectId source,
                                         ContextObjectId target,
                                         std::string kind,
                                         ContextMetadata metadata)
    : id_(id),
      source_(source),
      target_(target),
      kind_(std::move(kind)),
      metadata_(std::move(metadata)) {}

bool ContextMetadata::operator==(const ContextMetadata& other) const noexcept {
    return core.name == other.core.name &&
           core.label == other.core.label &&
           core.description == other.core.description &&
           core.tags == other.core.tags &&
           version == other.version &&
           classification == other.classification &&
           annotations == other.annotations;
}

}  // namespace ak::context
