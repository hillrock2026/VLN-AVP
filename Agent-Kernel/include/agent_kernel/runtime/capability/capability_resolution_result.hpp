// ============================================================
// Agent Kernel - CapabilityResolution
// ============================================================
// Runtime value object representing the outcome of a
// capability resolution attempt.
//
// CapabilityResolution is produced by ICapabilityResolver.
// It contains the resolution status and, on success,
// the resolved capability identity and ExecutionBinding.
//
// AK0023 Chapter 9.3 - CapabilityResolution
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include <agent_kernel/runtime/capability/capability_identifier.hpp>
#include <agent_kernel/runtime/capability/execution_binding.hpp>

namespace ak {

// ============================================================
// ResolutionStatus
// ============================================================
enum class ResolutionStatus : std::uint8_t {
    kResolved,              // Successfully resolved
    kCapabilityNotFound,    // No matching capability
    kVersionMismatch,       // Version constraint not satisfied
    kUnsupported,           // Capability not currently supported
    kResolverUnavailable,   // Resolver not available
    kBindingFailed,         // Binding could not be created
    kInternalError          // Unexpected error
};

// ============================================================
// ResolutionDiagnostics
// ============================================================
struct ResolutionDiagnostics {
    std::string message;
    std::vector<std::string> suggestedAlternatives;

    // Reserved for future:
    // std::string resolverVersion;
    // std::vector<std::string> details;
};

// ============================================================
// CapabilityResolution
// ============================================================
struct CapabilityResolution {
    CapabilityIdentifier capabilityID;
    ResolutionStatus status = ResolutionStatus::kCapabilityNotFound;
    ResolutionDiagnostics diagnostics;

    // Was resolution successful?
    [[nodiscard]] bool IsResolved() const noexcept {
        return status == ResolutionStatus::kResolved;
    }

    // The ExecutionBinding if resolved.
    ExecutionBinding binding;
};

}  // namespace ak