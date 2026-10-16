// ============================================================
// Agent Kernel - MemoryIdentity (Memory boundary)
// ============================================================
// Memory-owned opaque identity representation.
//
// P1-IS003 scope (Chapter 4.1 - Memory Identity, Chapter 16):
// - Memory is an independent architectural subsystem with its
//   own identity domain.
// - Domain, Object, Entry, and Reference identities are
//   distinct Memory-owned identity domains; they cannot be
//   mixed at compile time.
// - The identity value is provided by the P1-IS001 Kernel
//   Foundation (TypedKernelIdentity); the Foundation supplies
//   neutral mechanics only and does NOT own Memory identity.
//
// NON-responsibilities:
// - These identities are not Runtime identities and reference
//   no Runtime type.
// - Identity is not derived from provider technology and does
//   not transfer architectural ownership.
// ============================================================

#pragma once

#include <cstdint>

#include <agent_kernel/foundation/kernel_identity.hpp>

namespace ak::memory {

struct MemoryIdentityTag {};
struct MemoryDomainTag {};
struct MemoryObjectTag {};
struct MemoryEntryTag {};
struct MemoryReferenceTag {};

// Memory-owned identity domains.
using MemoryIdentity = ak::TypedKernelIdentity<MemoryIdentityTag>;
using MemoryDomainId = ak::TypedKernelIdentity<MemoryDomainTag>;
using MemoryObjectId = ak::TypedKernelIdentity<MemoryObjectTag>;
using MemoryEntryId = ak::TypedKernelIdentity<MemoryEntryTag>;
using MemoryReferenceId = ak::TypedKernelIdentity<MemoryReferenceTag>;

// Creates valid Memory identities. Default construction yields
// an invalid identity (value 0).
[[nodiscard]] inline MemoryIdentity MakeMemoryIdentity(std::uint64_t value) noexcept {
    return MemoryIdentity(value);
}
[[nodiscard]] inline MemoryDomainId MakeMemoryDomainId(std::uint64_t value) noexcept {
    return MemoryDomainId(value);
}
[[nodiscard]] inline MemoryObjectId MakeMemoryObjectId(std::uint64_t value) noexcept {
    return MemoryObjectId(value);
}
[[nodiscard]] inline MemoryEntryId MakeMemoryEntryId(std::uint64_t value) noexcept {
    return MemoryEntryId(value);
}
[[nodiscard]] inline MemoryReferenceId MakeMemoryReferenceId(std::uint64_t value) noexcept {
    return MemoryReferenceId(value);
}

}  // namespace ak::memory