// ============================================================
// Agent Kernel - ContextServices (Context boundary)
// ============================================================
// Context Service boundary: the SOLE architectural service
// boundary of Context.
//
// P1-IS004 scope (Chapter 13 - Service Architecture, Chapter
// 27):
// - External consumers interact with Context Objects only
//   through Context Services.
// - The required service responsibilities are represented
//   explicitly and testably as five Context-owned services:
//       Context Creation Service
//       Context Access Service
//       Context Update Service
//       Context Composition Service
//       Context Release Service
// - Services preserve Context ownership, enforce lifecycle and
//   state validity, preserve object consistency, preserve
//   boundary encapsulation, and return explicit result
//   semantics.
//
// NON-responsibilities:
// - Services do not coordinate Agent, Memory, Planner, or Tool.
// - Services do not execute, schedule, resolve, manage, or
//   publish Runtime behavior, and they access no Runtime
//   implementation.
// ============================================================

#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include <agent_kernel/context/context_identity.hpp>
#include <agent_kernel/context/context_objects.hpp>
#include <agent_kernel/context/context_result.hpp>
#include <agent_kernel/context/context_store.hpp>

namespace ak::context {

// ------------------------------------------------------------
// Context Creation Service
// ------------------------------------------------------------
// Establishes Context Objects, initializes them, establishes
// Context ownership, and prepares lifecycle participation.
// Creation SHALL NOT imply activation: an explicit activation
// request is required for participation.
class ContextCreationService {
public:
    explicit ContextCreationService(ContextStore& store) noexcept : store_(store) {}

    // Establishes a Context Object in lifecycle Created /
    // operational Uninitialized. Creation does not activate.
    [[nodiscard]] ContextResultValue<ContextObjectId> CreateObject(
        ContextObjectId id, std::string category, std::string content,
        ContextMetadata metadata);

    // Created -> Initialized (lifecycle) and
    // Uninitialized -> Ready (operational).
    [[nodiscard]] ContextResult InitializeObject(ContextObjectId id);

    // Initialized -> Active (lifecycle) and
    // Ready -> Active (operational).
    [[nodiscard]] ContextResult ActivateObject(ContextObjectId id);

    [[nodiscard]] std::size_t ObjectCount() const noexcept;

private:
    ContextStore& store_;
};

// ------------------------------------------------------------
// Context Access Service
// ------------------------------------------------------------
// Controlled access to execution context. Preserves object
// integrity, ownership, and architectural consistency by
// returning value copies and read-only views.
class ContextAccessService {
public:
    explicit ContextAccessService(const ContextStore& store) noexcept
        : store_(store) {}

    // Read-only inspection of a Context Object. Returns
    // kInvalid when the Object does not exist, kReleased when
    // the Object is released.
    [[nodiscard]] ContextResultValue<ContextObjectView> InspectObject(
        ContextObjectId id) const;

    // Enumerates Object identities (read-only).
    [[nodiscard]] ContextResultValue<std::vector<ContextObjectId>> ListObjects()
        const;

    [[nodiscard]] std::size_t ObjectCount() const noexcept;

private:
    const ContextStore& store_;
};

// ------------------------------------------------------------
// Context Update Service
// ------------------------------------------------------------
// Controlled evolution of execution context. Preserves
// ownership, lifecycle validity, state consistency, and
// structural integrity.
class ContextUpdateService {
public:
    explicit ContextUpdateService(ContextStore& store) noexcept : store_(store) {}

    // Active -> Updated (lifecycle) and Active -> Updating
    // (operational): controlled evolution begins.
    [[nodiscard]] ContextResult BeginUpdate(ContextObjectId id);

    // Applies a new working-state payload/metadata while the
    // Object is in lifecycle Updated / operational Updating.
    [[nodiscard]] ContextResult ApplyUpdate(ContextObjectId id,
                                            std::string content,
                                            ContextMetadata metadata);

    // Updated -> Active (lifecycle) and Updating -> Active
    // (operational): controlled evolution completes.
    [[nodiscard]] ContextResult CompleteUpdate(ContextObjectId id);

private:
    ContextStore& store_;
};

// ------------------------------------------------------------
// Context Composition Service
// ------------------------------------------------------------
// Composes Context Objects into larger execution-context
// representations through contextual relationships. Composition
// remains a Context responsibility.
class ContextCompositionService {
public:
    explicit ContextCompositionService(ContextStore& store) noexcept
        : store_(store) {}

    // Establishes a contextual relationship between two
    // non-released Context Objects.
    [[nodiscard]] ContextResultValue<ContextRelationshipId> ComposeRelationship(
        ContextRelationshipId relationship_id, ContextObjectId source,
        ContextObjectId target, std::string kind, ContextMetadata metadata);

    // Lists relationships in which the given Object participates
    // as source or target (read-only).
    [[nodiscard]] ContextResultValue<std::vector<ContextRelationship>>
    ListRelationshipsOf(ContextObjectId object_id) const;

    [[nodiscard]] std::size_t RelationshipCount() const noexcept;

private:
    ContextStore& store_;
};

// ------------------------------------------------------------
// Context Release Service
// ------------------------------------------------------------
// Retires Context Objects. Release preserves lifecycle
// semantics and is irreversible: a Released Context Object
// rejects operational access and never returns to an
// operational state.
class ContextReleaseService {
public:
    explicit ContextReleaseService(ContextStore& store) noexcept : store_(store) {}

    // Active/Updated -> Released (lifecycle) and
    // Active -> Released (operational). Terminal.
    [[nodiscard]] ContextResult ReleaseObject(ContextObjectId id);

private:
    ContextStore& store_;
};

}  // namespace ak::context
