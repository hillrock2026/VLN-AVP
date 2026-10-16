// ============================================================
// Agent Kernel - ContextIdentity (Context boundary)
// ============================================================
// Context-owned opaque identity representation.
//
// P1-IS004 scope (Chapter 9 - Context Identity, Chapter 27):
// - Context is an independent architectural subsystem with its
//   own identity domain.
// - Every Context Object carries a stable Context-owned
//   identity for its architectural lifetime.
// - Context Object and Context Relationship identities are
//   distinct Context-owned identity domains; they cannot be
//   mixed at compile time.
// - The identity value is provided by the P1-IS001 Kernel
//   Foundation (TypedKernelIdentity); the Foundation supplies
//   neutral mechanics only and does NOT own Context identity.
//
// NON-responsibilities:
// - These identities are not Memory, Agent, or Runtime
//   identities and reference no Runtime type.
// - Identity never transfers architectural ownership and is
//   not derived from storage or provider technology.
// ============================================================

#pragma once

#include <cstdint>

#include <agent_kernel/foundation/kernel_identity.hpp>

namespace ak::context {

struct ContextIdentityTag {};
struct ContextObjectTag {};
struct ContextRelationshipTag {};

// Context-owned identity domains.
using ContextIdentity = ak::TypedKernelIdentity<ContextIdentityTag>;
using ContextObjectId = ak::TypedKernelIdentity<ContextObjectTag>;
using ContextRelationshipId = ak::TypedKernelIdentity<ContextRelationshipTag>;

// Creates valid Context identities. Default construction yields
// an invalid identity (value 0).
[[nodiscard]] inline ContextIdentity MakeContextIdentity(std::uint64_t value) noexcept {
    return ContextIdentity(value);
}
[[nodiscard]] inline ContextObjectId MakeContextObjectId(std::uint64_t value) noexcept {
    return ContextObjectId(value);
}
[[nodiscard]] inline ContextRelationshipId MakeContextRelationshipId(
    std::uint64_t value) noexcept {
    return ContextRelationshipId(value);
}

}  // namespace ak::context
