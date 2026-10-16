// ============================================================
// Agent Kernel - RuntimeExecutionAuthorityHandle (integration layer)
// ============================================================
// K0-BLOCKER-REMEDIATION-05 (INV-K0-FWA-RUNTIME-AUTHORITY):
// the Kernel-issued execution authority token consumed by the
// production FWA composition.
//
// Kernel-owned construction: the handle has NO public constructor
// that accepts a port. The only production issuer is
// ak::runtime_integration::IssueRuntimeExecutionAuthority(ak::runtime::Runtime&),
// which binds a REAL RuntimePublicApiAdapter (final, constructible
// only from a Runtime&) to a REAL Kernel Runtime. A production
// caller therefore CANNOT choose, replace, subclass, inject or
// otherwise supply a Runtime execution authority: there is no
// public conversion from any
// ak::agent::RuntimeInteractionPort implementation to this type.
//
// FWA consumes this handle through its configuration; the
// composition only reaches the Kernel-bound port through
// RuntimeExecutionAuthorityHandle::Port() and never names the
// injectable interface itself.
//
// This header is Runtime-free (the only Runtime reference is a
// forward declaration) and header-only, so Agent-side consumers
// need no Runtime link to hold or move the handle.
// ============================================================

#pragma once

#include <memory>
#include <utility>

#include <agent_kernel/agent/runtime/runtime_interaction_port.hpp>

namespace ak::runtime {

// Forward declaration only (no Runtime type crosses the boundary).
class Runtime;

}  // namespace ak::runtime

namespace ak::runtime_integration {

class RuntimePublicApiAdapter;

// ============================================================
// RuntimeExecutionAuthorityHandle
// ============================================================
// Move-only value. Default-constructed = unbound (no authority):
// an unbound handle is a deterministic failure at submission time,
// never a fabricated execution.
class RuntimeExecutionAuthorityHandle {
public:
    RuntimeExecutionAuthorityHandle() noexcept = default;

    RuntimeExecutionAuthorityHandle(
        RuntimeExecutionAuthorityHandle&& other) noexcept = default;
    RuntimeExecutionAuthorityHandle& operator=(
        RuntimeExecutionAuthorityHandle&& other) noexcept = default;

    RuntimeExecutionAuthorityHandle(
        const RuntimeExecutionAuthorityHandle&) = delete;
    RuntimeExecutionAuthorityHandle& operator=(
        const RuntimeExecutionAuthorityHandle&) = delete;

    // True when the Kernel factory issued a Runtime-bound port.
    [[nodiscard]] bool IsBound() const noexcept {
        return port_ != nullptr;
    }

    // The Kernel-bound submission port. Calling this on an unbound
    // handle is a caller error; IsBound() MUST be checked first.
    [[nodiscard]] ak::agent::RuntimeInteractionPort& Port()
        const noexcept {
        return *port_;
    }

private:
    friend RuntimeExecutionAuthorityHandle
    IssueRuntimeExecutionAuthority(ak::runtime::Runtime& runtime);

    explicit RuntimeExecutionAuthorityHandle(
        std::unique_ptr<ak::agent::RuntimeInteractionPort> port) noexcept
        : port_(std::move(port)) {}

    std::unique_ptr<ak::agent::RuntimeInteractionPort> port_;
};

// The ONLY production issuance path (Kernel-owned construction).
// Defined in the integration layer (runtime_public_api_adapter.cpp);
// callers link agent_kernel_runtime_integration.
[[nodiscard]] RuntimeExecutionAuthorityHandle
IssueRuntimeExecutionAuthority(ak::runtime::Runtime& runtime);

}  // namespace ak::runtime_integration
