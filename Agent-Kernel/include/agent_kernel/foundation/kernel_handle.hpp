// ============================================================
// Agent Kernel - KernelHandle (Foundation Layer)
// ============================================================
// Ownership-neutral, type-safe stable reference.
//
// P1-IS001 Kernel Foundation scope:
// - A KernelHandle is a non-owning value reference: it is
//   copyable, comparable, and usable in containers.
// - It carries the referenced type, an identity value, and a
//   generation counter to detect stale references.
//
// NON-responsibilities (P1-IS001):
// - A KernelHandle does NOT extend object lifetime.
// - A KernelHandle does NOT transfer or grant architectural
//   ownership.
// - A KernelHandle is NOT a Runtime reference and does NOT
//   resolve Runtime capabilities.
//
// Resolution to a concrete pointer is owner-specific and is
// deliberately NOT part of the neutral Foundation surface.
// ============================================================

#pragma once

#include <cstdint>
#include <functional>

namespace ak {

// ============================================================
// KernelHandle
// ============================================================
template <typename ObjectType, typename IDType>
class KernelHandle {
public:
    using ObjectT = ObjectType;
    using IDT = IDType;

    // -- Construction --
    KernelHandle() noexcept = default;

    explicit KernelHandle(IDType id, std::uint64_t generation) noexcept
        : id_(id), generation_(generation) {}

    // -- Identity --
    [[nodiscard]] IDType GetID() const noexcept { return id_; }
    [[nodiscard]] std::uint64_t GetGeneration() const noexcept { return generation_; }

    // -- Comparison --
    auto operator<=>(const KernelHandle&) const = default;

    // -- Validity --
    [[nodiscard]] bool IsValid() const noexcept {
        return generation_ != 0;
    }

private:
    IDType id_;
    std::uint64_t generation_ = 0;
};

}  // namespace ak

// ============================================================
// std::hash specialization
// ============================================================
namespace std {
template <typename T, typename ID>
struct hash<ak::KernelHandle<T, ID>> {
    size_t operator()(const ak::KernelHandle<T, ID>& handle) const noexcept {
        return hash<ID>()(handle.GetID());
    }
};
}  // namespace std