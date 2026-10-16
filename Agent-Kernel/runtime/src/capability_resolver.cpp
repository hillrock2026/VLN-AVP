// ============================================================
// FIX0004 — Runtime Capability Resolver Implementation
// ============================================================
// Aligned with AK0033 public API contract.
//
// AK0033 §7.2:  Resolve() returns CapabilityBinding
// AK0033 §7.6:  On failure, throws std::runtime_error
// AK0033 §7.7:  Strong Exception Guarantee
// AK0033 §7.8:  Synchronous, single-threaded, deterministic
// AK0033 §10:   Registry operations are internal

#include <capability_resolver.h>

#include <algorithm>
#include <stdexcept>
#include <string>

namespace ak::runtime {

// ============================================================
// Construction / Destruction
// ============================================================

CapabilityResolver::CapabilityResolver() = default;

CapabilityResolver::~CapabilityResolver() = default;

// ============================================================
// AK0033 §7 — Resolve API
// ============================================================

ak::CapabilityBinding CapabilityResolver::Resolve(
    const ak::TaskExecutionDescriptor& descriptor) {

    const std::string capabilityName = ExtractCapabilityName(descriptor);

    // AK0033 §13.2: Validate descriptor — empty name is invalid.
    if (capabilityName.empty()) {
        throw std::runtime_error(
            "CapabilityResolver::Resolve: "
            "TaskExecutionDescriptor has empty capability name.");
    }

    // AK0033 §14: Registry lookup.
    auto it = registry_.find(capabilityName);
    if (it == registry_.end()) {
        throw std::runtime_error(
            "CapabilityResolver::Resolve: "
            "Capability not found: " + capabilityName);
    }

    // AK0033 §15-16: Version matching & constraint evaluation.
    // P0R0004 implementation returns the registered binding directly
    // (single version per name — no disambiguation needed).

    // AK0033 §6 stage 6: Return CapabilityBinding.
    return it->second;
}

// ============================================================
// AK0033 §7.7 — IsResolvable (non-mutating pre-check)
// ============================================================

bool CapabilityResolver::IsResolvable(
    const ak::TaskExecutionDescriptor& descriptor) const {

    const std::string capabilityName = ExtractCapabilityName(descriptor);

    // AK0033 §7.7: Returns true when the descriptor can be resolved,
    // false otherwise. Does NOT perform full resolution.
    return !capabilityName.empty() &&
           (registry_.find(capabilityName) != registry_.end());
}

// ============================================================
// AK0033 §10 — Registry Operations (internal)
// ============================================================


void CapabilityResolver::Register(
    const std::string& name,
    const std::string& provider,
    const ak::CapabilityInvoker& invoker) {

    ak::CapabilityBinding binding(provider);
    binding.invoker = invoker;
    registry_[name] = std::move(binding);
}
void CapabilityResolver::Register(
    const std::string& name,
    const std::string& provider) {

    ak::CapabilityBinding binding(provider);
    registry_[name] = std::move(binding);
}

void CapabilityResolver::Unregister(const std::string& name) {
    registry_.erase(name);
}

bool CapabilityResolver::Contains(const std::string& name) const {
    return registry_.find(name) != registry_.end();
}

std::size_t CapabilityResolver::RegistrySize() const noexcept {
    return registry_.size();
}

// ============================================================
// Private Helpers
// ============================================================

std::string CapabilityResolver::ExtractCapabilityName(
    const ak::TaskExecutionDescriptor& descriptor) {

    // The capability name is stored in descriptor.capability.name.
    return descriptor.capability.name;
}

}  // namespace ak::runtime
