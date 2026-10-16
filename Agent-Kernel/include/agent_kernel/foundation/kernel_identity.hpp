// ============================================================
// Agent Kernel - KernelIdentity (Foundation Layer)
// ============================================================
// Opaque, immutable identity value representation.
//
// P1-IS001 Kernel Foundation scope:
// - Provides an architecture-neutral identity value that any
//   architectural owner may use for owner-scoped identity.
// - KernelIdentity is a value type: it is copied by value,
//   compared, hashed, and serialized to a string.
// - It is opaque to modification: the wrapped value is assigned
//   at construction and never changes.
//
// NON-responsibilities (P1-IS001):
// - KernelIdentity is NOT an architectural object.
// - It does NOT absorb, transfer, or determine architectural
//   ownership.
// - It is NOT a Runtime identity and does NOT reference Runtime
//   types.
// - Identity ownership remains with the architectural owner that
//   assigns and holds the value.
// ============================================================

#pragma once

#include <cstdint>
#include <functional>
#include <string>

namespace ak {

// ============================================================
// KernelIdentity
// ============================================================
// Neutral opaque identity value.
//
// A default-constructed KernelIdentity is invalid (value 0) so
// absent identities can be represented without a separate
// optional wrapper.
class KernelIdentity {
public:
    using ValueType = std::uint64_t;

    KernelIdentity() noexcept = default;

    explicit KernelIdentity(ValueType value) noexcept : value_(value) {}

    // -- Validity --
    [[nodiscard]] bool IsValid() const noexcept { return value_ != 0; }

    // -- Opaque access --
    [[nodiscard]] ValueType Value() const noexcept { return value_; }

    // -- Serialization --
    [[nodiscard]] std::string ToString() const { return std::to_string(value_); }

    // -- Comparison --
    auto operator<=>(const KernelIdentity&) const = default;

private:
    ValueType value_ = 0;
};

// ============================================================
// TypedKernelIdentity<Tag>
// ============================================================
// Type-safe identity for one owner boundary.
//
// An architectural owner may instantiate
// TypedKernelIdentity<AgentTag> to obtain a distinct identity
// type that cannot be mixed with another owner's identity at
// compile time. The tag carries no semantics inside the
// Foundation; it exists only to keep owner domains separate.
template <typename Tag>
class TypedKernelIdentity : public KernelIdentity {
public:
    using KernelIdentity::KernelIdentity;
};

}  // namespace ak

// ============================================================
// std::hash specializations
// ============================================================
namespace std {
template <>
struct hash<ak::KernelIdentity> {
    size_t operator()(const ak::KernelIdentity& identity) const noexcept {
        return hash<ak::KernelIdentity::ValueType>()(identity.Value());
    }
};

template <typename Tag>
struct hash<ak::TypedKernelIdentity<Tag>> {
    size_t operator()(const ak::TypedKernelIdentity<Tag>& identity) const noexcept {
        return hash<ak::KernelIdentity::ValueType>()(identity.Value());
    }
};
}  // namespace std