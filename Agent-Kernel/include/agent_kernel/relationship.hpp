// ============================================================
// Agent Kernel — Relationship
// ============================================================
// Type-safe relationship descriptors for Kernel Object
// composition and association.
//
// This header defines the relationship types used in the
// Kernel Domain Model (AK0011 Chapter 4). It provides
// compile-time documentation of ownership semantics.
// ============================================================

#pragma once

#include <memory>
#include <vector>

#include <agent_kernel/object_id.hpp>

namespace ak {

// ============================================================
// OwnershipTag — documents ownership intent at compile time
// ============================================================

// Exclusive ownership — parent creates and destroys child.
// Corresponds to std::unique_ptr<T>.
struct ExclusiveOwnership {};

// Observed reference — non-owning, caller guarantees lifetime.
// Corresponds to T& or T*.
struct ObservedReference {};

// Shared observation — for observer pattern attachments.
// Corresponds to std::shared_ptr<T>.
struct SharedObservation {};

// ============================================================
// DependencyDescriptor — describes Task-to-Task dependency
// ============================================================
struct DependencyDescriptor {
    TaskID from;   // Task that depends
    TaskID to;     // Task that must complete first
};

// ============================================================
// Composition helpers
// ============================================================

// OwningCollection enforces exclusive ownership semantics
// for a set of child Kernel Objects.
template <typename T>
using OwningCollection = std::vector<std::unique_ptr<T>>;

// Non-owning reference to a Kernel Object.
template <typename T>
using ObserverRef = T*;

}  // namespace ak
