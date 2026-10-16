// ============================================================
// FIX0004 — Runtime Capability Resolver
// ============================================================
// Concrete implementation per AK0033 §6.2.
//
// Public API (AK0033 §6.2 lines 416-424):
//   CapabilityResolver()             — Constructor
//   ~CapabilityResolver()            — Destructor
//   Resolve(descriptor)              — Returns CapabilityBinding
//   IsResolvable(descriptor)         — Pre-check without resolution
//
// All other operations (Register, Unregister, Contains,
// RegistrySize) are private implementation details per
// AK0033 §6.2 lines 429-432 and §10.
//
// Failure handling: Resolve() throws std::runtime_error
// on failure (AK0033 §7.6 line 483).
//
// Responsibilities:
// - Validate incoming descriptors
// - Resolve capability identity to CapabilityBinding
// - Generate deterministic resolution results
//
// NON-responsibilities:
// - Does NOT execute capabilities (Executor — P0R0003)
// - Does NOT schedule tasks (Scheduler — P0R0002)
// - Does NOT manage Runtime lifecycle
// - Does NOT publish events (EventBus — P0R0005)
//
// Conforms to AK0033 (Runtime Capability Resolver Specification).
// Owned by Runtime per AK0030-I4 Revision 2.
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <unordered_map>

#include <capability_binding.h>
#include <agent_kernel/task/task_execution_descriptor.hpp>

namespace ak::runtime {

class Runtime;

// ============================================================
// CapabilityResolver — Concrete Runtime capability resolver
// ============================================================
// AK0033 §6.2: Resolve() and IsResolvable() are the sole
// public APIs of the CapabilityResolver.
class CapabilityResolver {
public:
    CapabilityResolver();
    ~CapabilityResolver();

    CapabilityResolver(const CapabilityResolver&) = delete;
    CapabilityResolver& operator=(const CapabilityResolver&) = delete;
    CapabilityResolver(CapabilityResolver&&) = delete;
    CapabilityResolver& operator=(CapabilityResolver&&) = delete;

    // ---- AK0033 §6.2 Public API ----

    // Resolve a TaskExecutionDescriptor to a CapabilityBinding.
    // On failure, throws std::runtime_error (AK0033 §7.6).
    [[nodiscard]] ak::CapabilityBinding Resolve(
        const ak::TaskExecutionDescriptor& descriptor);

    // Non-mutating pre-check: returns true when the descriptor
    // can be resolved, false otherwise (AK0033 §7.7-7.8).
    // Does NOT perform full resolution.
    [[nodiscard]] bool IsResolvable(
        const ak::TaskExecutionDescriptor& descriptor) const;

private:
    // ---- AK0033 §10 — Registry operations (internal) ----

    // Register a capability binding for resolution (no invoker:
    // resolution succeeds; real invocation fails deterministically).
    void Register(const std::string& name,
                  const std::string& provider);

    // Register a capability binding with an executable invoker
    // (TASK 2 §14 / §16; TASK 3.1 §9.1). Called only by Runtime
    // (friend) through the sanctioned registration path.
    void Register(const std::string& name,
                  const std::string& provider,
                  const ak::CapabilityInvoker& invoker);

    // Remove a capability from the registry.
    void Unregister(const std::string& name);

    // Check if a capability name is registered.
    [[nodiscard]] bool Contains(const std::string& name) const;

    // Number of registered capabilities.
    [[nodiscard]] std::size_t RegistrySize() const noexcept;

    // Friend for test access to private registry methods.
    friend struct CapabilityResolverTestAccess;

    // Runtime facade is the sanctioned production registration
    // path (TASK 3.1 §16); registry operations remain private.
    friend class Runtime;

    // Extract the capability name from a TaskExecutionDescriptor.
    [[nodiscard]] static std::string ExtractCapabilityName(
        const ak::TaskExecutionDescriptor& descriptor);

    // In-memory capability registry: name → CapabilityBinding.
    std::unordered_map<std::string, ak::CapabilityBinding> registry_;
};

}  // namespace ak::runtime
