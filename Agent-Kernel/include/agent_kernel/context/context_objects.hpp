// ============================================================
// Agent Kernel - ContextObjects (Context boundary)
// ============================================================
// Context-owned object model representations.
//
// P1-IS004 scope (Chapter 12 - Context Objects, Chapter 27):
// - ContextObject is the unit of execution context and
//   intelligent working state; its payload is opaque at the
//   architectural boundary (read-only content).
// - ContextRelationship carries contextual relationships
//   between Context Objects.
// - ContextMetadata is extensible, implementation-independent
//   execution metadata.
// - Every Context Object possesses a stable Context-owned
//   identity and carries its own Context-owned lifecycle and
//   operational state; external components cannot mutate them.
// - Context Objects SHALL NOT become Memory Objects, Runtime
//   Objects, Agent lifecycle objects, Planner execution
//   objects, or Tool execution objects.
//
// NON-responsibilities:
// - These are Context-owned value representations; they do not
//   coordinate peers and reference no Runtime type.
// - The payload is NOT a prompt buffer, LLM context window,
//   conversation-history store, cache, or knowledge-retention
//   representation: those techniques do not define Context
//   identity or ownership (P1-IS004 Chapter 6 / 15).
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

#include <agent_kernel/context/context_identity.hpp>
#include <agent_kernel/context/context_lifecycle.hpp>
#include <agent_kernel/context/context_operational_state.hpp>
#include <agent_kernel/context/context_state.hpp>
#include <agent_kernel/foundation/kernel_metadata.hpp>

namespace ak::context {

// ------------------------------------------------------------
// ContextMetadata - extensible, implementation-independent
// ------------------------------------------------------------
struct ContextMetadata {
    // Neutral core (Foundation value mechanics only).
    ak::KernelMetadata core;
    // Version identifier.
    std::uint64_t version = 1;
    // Optional classification.
    std::string classification;
    // Extensible, implementation-independent annotations.
    std::vector<std::string> annotations;

    // Structural equality for verification (field-wise).
    [[nodiscard]] bool operator==(const ContextMetadata& other) const noexcept;
    [[nodiscard]] bool operator!=(const ContextMetadata& other) const noexcept {
        return !(*this == other);
    }
};

// ------------------------------------------------------------
// ContextObject - unit of execution context / working state
// ------------------------------------------------------------
class ContextObject {
public:
    ContextObject() = default;
    ContextObject(ContextObjectId id, std::string category, std::string content,
                  ContextMetadata metadata);

    // -- Read-only boundary surface --
    [[nodiscard]] ContextObjectId GetId() const noexcept { return id_; }
    [[nodiscard]] const std::string& GetCategory() const noexcept {
        return category_;
    }
    [[nodiscard]] const ContextMetadata& GetMetadata() const noexcept {
        return metadata_;
    }
    // Read-only view of the opaque working-state payload.
    [[nodiscard]] const std::string& Content() const noexcept { return content_; }
    // Read-only lifecycle/state observation: Context retains
    // ownership; mutation is possible only through Context
    // Services.
    [[nodiscard]] ContextLifecycleState GetLifecycleState() const noexcept {
        return lifecycle_.GetState();
    }
    [[nodiscard]] ContextOperationalState GetOperationalState() const noexcept {
        return operational_.GetState();
    }

private:
    ContextObjectId id_;
    std::string category_;
    std::string content_;
    ContextMetadata metadata_;
    ContextLifecycle lifecycle_;
    ContextOperationalStateMachine operational_;

    // Only Context Services may drive the per-object lifecycle
    // and operational state and mutate the working state.
    friend class ContextCreationService;
    friend class ContextUpdateService;
    friend class ContextReleaseService;
};

// ------------------------------------------------------------
// ContextRelationship - contextual relationship between objects
// ------------------------------------------------------------
class ContextRelationship {
public:
    ContextRelationship() = default;
    ContextRelationship(ContextRelationshipId id, ContextObjectId source,
                       ContextObjectId target, std::string kind,
                       ContextMetadata metadata);

    [[nodiscard]] ContextRelationshipId GetId() const noexcept { return id_; }
    [[nodiscard]] ContextObjectId GetSourceId() const noexcept { return source_; }
    [[nodiscard]] ContextObjectId GetTargetId() const noexcept { return target_; }
    [[nodiscard]] const std::string& GetKind() const noexcept { return kind_; }
    [[nodiscard]] const ContextMetadata& GetMetadata() const noexcept {
        return metadata_;
    }

private:
    ContextRelationshipId id_;
    ContextObjectId source_;
    ContextObjectId target_;
    std::string kind_;
    ContextMetadata metadata_;

    friend class ContextCompositionService;
};

// ------------------------------------------------------------
// ContextObjectView - controlled read-only access copy
// ------------------------------------------------------------
// Value copy returned by the Access Service. External
// components receive a snapshot of execution context without
// direct access to Context Object internals.
struct ContextObjectView {
    ContextObjectId id;
    std::string category;
    std::string content;
    ContextMetadata metadata;
    ContextLifecycleState lifecycle = ContextLifecycleState::kCreated;
    ContextOperationalState operational = ContextOperationalState::kUninitialized;
};

}  // namespace ak::context
