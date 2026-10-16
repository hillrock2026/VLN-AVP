// ============================================================
// Agent Kernel - KernelObject (Foundation Layer)
// ============================================================
// Neutral object mechanics shared by owner-specific
// representations.
//
// P1-IS001 Kernel Foundation scope:
// - KernelObject provides neutral mechanics only: identity
//   access and metadata access.
// - Concrete owner-specific objects may inherit the interface
//   or, preferably, compose the Foundation value types they
//   need (KernelMetadata, KernelIdentity, ObserverRegistry).
//
// NON-responsibilities (P1-IS001):
// - KernelObject is an implementation representation, NOT a new
//   root architectural owner.
// - It does NOT provide lifecycle authority: there is no
//   Initialize/Destroy and no state model on the base.
// - It does NOT provide subsystem state semantics.
// - It does NOT coordinate subsystems.
// - Inheritance from this representation does NOT grant
//   architectural ownership; composition is preferred where
//   inheritance would blur architectural identity.
// ============================================================

#pragma once

#include <cstdint>

#include <agent_kernel/foundation/kernel_identity.hpp>
#include <agent_kernel/foundation/kernel_metadata.hpp>

namespace ak {

// ============================================================
// KernelObject - abstract neutral object interface
// ============================================================
class KernelObject {
public:
    virtual ~KernelObject() noexcept = default;

    // -- Identity --
    [[nodiscard]] virtual KernelIdentity GetIdentity() const noexcept = 0;

    // -- Metadata --
    [[nodiscard]] virtual const KernelMetadata& GetMetadata() const noexcept = 0;
    virtual void SetMetadata(const KernelMetadata& metadata) = 0;
};

// ============================================================
// TypedKernelObject - CRTP helper for typed identity access
// ============================================================
// Owner-specific objects may inherit from this CRTP helper to
// obtain type-safe identity access without virtual dispatch.
//
// Example:
//   class MyObject : public TypedKernelObject<MyObject, MyID> { ... };
//
// T = concrete class, ID = owner-specific identity type that
// exposes Value(). The ID type is supplied by the owner; the
// Foundation only requires the Value() accessor.
template <typename T, typename ID>
class TypedKernelObject : public KernelObject {
public:
    using IDType = ID;

    // -- Typed identity access (non-virtual, no dispatch) --
    [[nodiscard]] ID GetID() const noexcept {
        return id_;
    }

    [[nodiscard]] std::uint64_t GetIDValue() const noexcept {
        return id_.Value();
    }

    // -- Neutral KernelObject interface --
    [[nodiscard]] KernelIdentity GetIdentity() const noexcept override {
        return KernelIdentity(id_.Value());
    }

protected:
    explicit TypedKernelObject(ID id) noexcept : id_(id) {}

    // Move support
    TypedKernelObject(TypedKernelObject&&) noexcept = default;
    TypedKernelObject& operator=(TypedKernelObject&&) noexcept = default;

private:
    ID id_;
};

}  // namespace ak