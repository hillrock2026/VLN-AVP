// ============================================================
// Agent Kernel - KernelContracts (Foundation Layer)
// ============================================================
// Architecture-neutral implementation contracts.
//
// P1-IS001 Kernel Foundation scope:
// - KernelContracts provides documentation-as-code contract
//   support for neutral Foundation mechanics.
// - Contracts are expressed through generic traits and static
//   assertions, not through base classes.
//
// NON-responsibilities (P1-IS001):
// - A kernel contract is implementation support, NOT a
//   replacement for the AK0040-AK0045 architectural contracts.
// - No contract here names Agent, Memory, Context, Planner,
//   Tool, or Runtime types.
// - Contracts do not grant architectural ownership or
//   coordination authority.
// ============================================================

#pragma once

#include <type_traits>

#include <agent_kernel/foundation/kernel_identity.hpp>

namespace ak {

// ============================================================
// IdentityContract
// ============================================================
// A type satisfies the neutral identity contract when it is a
// KernelIdentity or a TypedKernelIdentity<...>.
//
// Architectural owners are NOT required to use these identity
// types; the trait exists so generic Foundation mechanics can
// be written against the neutral identity surface.

template <typename T>
struct is_kernel_identity : std::false_type {};

template <>
struct is_kernel_identity<KernelIdentity> : std::true_type {};

template <typename Tag>
struct is_kernel_identity<TypedKernelIdentity<Tag>> : std::true_type {};

template <typename T>
inline constexpr bool is_kernel_identity_v = is_kernel_identity<T>::value;

// ============================================================
// Contract verification (compiles to nothing in Release)
// ============================================================

// Assert that a type is a valid neutral identity type.
template <typename ID>
constexpr void AssertValidIdentity() noexcept {
    static_assert(is_kernel_identity_v<ID>,
                  "Type is not a valid Kernel Foundation identity");
}

}  // namespace ak