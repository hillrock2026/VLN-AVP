// ============================================================
// AK0033 §8.2 / §9.2 — CapabilityBinding
// ============================================================
// Canonical return type of CapabilityResolver::Resolve().
//
// CapabilityBinding represents the executable result returned
// by the Resolver. It is a Runtime object, immutable after
// construction, and contains sufficient information for the
// Executor to invoke the selected Capability.
//
// AK0033 §8.2 — CapabilityBinding structure:
//   struct CapabilityBinding {
//       std::string providerName;
//   };
//
// AK0033 §9.3: CapabilityBinding is owned by Runtime.
// AK0033 §9.3: Executor receives a read-only binding.
// ============================================================

#pragma once

#include <functional>
#include <optional>
#include <string>

namespace ak {

// ============================================================
// CapabilityInvoker — executable capability callable
// ============================================================
// TASK 2 §16 / TASK 3.1 §9.3: the real executable capability.
// Registered through Runtime::RegisterCapability and invoked by
// the Executor with the invocation payload. Returns the
// capability output string. Absence of an invoker means the
// capability can be resolved but cannot be executed.
using CapabilityInvoker =
    std::function<std::string(const std::string& payload)>;


// ============================================================
// CapabilityBinding — Resolver result value object
// ============================================================
// Immutable after construction. Identifies which capability
// provider was selected during resolution.
//
// Per AK0033 §8.2, the contract requires at minimum a
// providerName. Implementations may wrap additional fields
// internally (AK0033 §9.2).
// ============================================================
struct CapabilityBinding {
    // Provider namespace (e.g., "openai", "local", "plugin")
    std::string providerName;

    // Default constructor — empty providerName.
    CapabilityBinding() = default;

    // Construct with a provider name.
    explicit CapabilityBinding(std::string name)
        : providerName(std::move(name)) {}

    // Optional executable capability (AK0033 §9.2 wrap allowance;
    // TASK 3.1 §9.2). When absent, resolution succeeds but real
    // invocation fails deterministically (TASK 2 §16).
    std::optional<CapabilityInvoker> invoker;
};

}  // namespace ak
