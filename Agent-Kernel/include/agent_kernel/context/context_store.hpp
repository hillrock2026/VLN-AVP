// ============================================================
// Agent Kernel - ContextStore (Context boundary)
// ============================================================
// Context-owned collections of Context Objects and Context
// Relationships.
//
// P1-IS004 scope (Chapter 12, Chapter 27):
// - All collections are private to the Context implementation
//   boundary and are mutated only through Context Services.
// - Containment is mechanical (Foundation OwnerScopedRegistry);
//   it does not transfer architectural ownership to the
//   Foundation.
// - Context Objects remain Context-owned for their whole
//   lifecycle; ownership terminates only at Released.
//
// NON-responsibilities:
// - ContextStore is not a Memory store, a Runtime repository,
//   or a global registry.
// - It is not a service locator, capability resolver, or
//   knowledge-retention system.
// ============================================================

#pragma once

#include <agent_kernel/context/context_objects.hpp>
#include <agent_kernel/foundation/kernel_registry.hpp>

namespace ak::context {

class ContextStore {
public:
    ContextStore() = default;

private:
    ak::OwnerScopedRegistry<ContextObjectId, ContextObject> objects_;
    ak::OwnerScopedRegistry<ContextRelationshipId, ContextRelationship>
        relationships_;

    friend class ContextCreationService;
    friend class ContextAccessService;
    friend class ContextUpdateService;
    friend class ContextCompositionService;
    friend class ContextReleaseService;
};

}  // namespace ak::context
