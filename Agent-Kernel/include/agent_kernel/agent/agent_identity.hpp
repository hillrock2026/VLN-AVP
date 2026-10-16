// ============================================================
// Agent Kernel - AgentIdentity (Agent boundary)
// ============================================================
// Agent-owned opaque identity representation.
//
// P1-IS002 scope (Chapter 5 - Agent Identity):
// - The Agent is represented as a first-class implementation
//   boundary with an independently owned identity.
// - Agent identity is independent from Runtime object identity
//   and from Memory/Context/Planner/Tool object identity.
// - The identity value is provided by the P1-IS001 Kernel
//   Foundation (TypedKernelIdentity); the Foundation supplies
//   neutral mechanics only and does NOT own Agent identity.
//
// NON-responsibilities:
// - AgentIdentity is not a Runtime identity and references no
//   Runtime type.
// - It does not transfer architectural ownership.
// ============================================================

#pragma once

#include <cstdint>

#include <agent_kernel/foundation/kernel_identity.hpp>

namespace ak::agent {

// Tag that keeps the Agent identity domain distinct from every
// other owner's identity domain at compile time.
struct AgentIdentityTag {};

// Agent-owned identity: a typed Foundation identity value.
using AgentIdentity = ak::TypedKernelIdentity<AgentIdentityTag>;

// Creates a valid Agent identity. An invalid identity (value 0)
// is available through default construction.
[[nodiscard]] inline AgentIdentity MakeAgentIdentity(std::uint64_t value) noexcept {
    return AgentIdentity(value);
}

}  // namespace ak::agent
