// ============================================================
// Agent Kernel - CapabilityIdentifier
// ============================================================
// Identity value type for Runtime capabilities.
//
// CapabilityIdentifier identifies a specific capability
// that can satisfy a TaskExecutionDescriptor.
// It does NOT reference Plugin or Runtime objects.
//
// AK0023 Chapter 9.1 - CapabilityIdentifier
// ============================================================

#pragma once

#include <cstdint>
#include <string>

namespace ak {

// ============================================================
// CapabilityVersion
// ============================================================
struct CapabilityVersion {
    std::uint32_t major = 0;
    std::uint32_t minor = 0;
    std::uint32_t patch = 0;

    // auto operator<=>(const CapabilityVersion&) const = default;
};

// ============================================================
// CapabilityIdentifier
// ============================================================
struct CapabilityIdentifier {
    // Canonical capability name (e.g., llm.chat, code.execute)
    std::string name;

    // Provider namespace (e.g., openai, local, plugin)
    std::string provider;

    // Resolved version of this capability
    std::uint32_t version = 1;
};

}  // namespace ak