// ============================================================
// Agent Kernel - ExecutionBinding
// ============================================================
// Runtime value object representing a resolved capability
// ready for execution.
//
// ExecutionBinding is immutable after creation. It is
// produced by the Capability Resolver and consumed by
// the Executor.
//
// ExecutionBinding is NOT owned by Task.
// ExecutionBinding does NOT contain executable code.
//
// AK0023 Chapter 6 - ExecutionBinding
// ============================================================

#pragma once

#include <cstdint>
#include <optional>
#include <string>

#include <agent_kernel/runtime/capability/capability_identifier.hpp>
#include <capability_binding.h>

namespace ak {

// ============================================================
// BindingStatus
// ============================================================
enum class BindingStatus : std::uint8_t {
    kReady,     // Binding is ready for execution
    kStale,     // Binding may no longer be valid
    kInvalid    // Binding is not usable
};

// ============================================================
// ExecutionBinding
// ============================================================
struct ExecutionBinding {
    CapabilityIdentifier capabilityID;
    BindingStatus status = BindingStatus::kReady;
    CapabilityVersion capabilityVersion;


    // Optional invocation payload (TASK 2 §15; TASK 3.1 §9.2).
    // Transported to the actual capability invocation boundary
    // without silent loss.
    std::optional<std::string> payload;

    // Optional executable capability (TASK 2 §16; TASK 3.1 §9.3).
    // When absent, resolution succeeds but real invocation fails
    // deterministically.
    std::optional<ak::CapabilityInvoker> invoker;
    // Reserved for future:
    // std::unordered_map metadata;
    // ResolutionDiagnostics diagnostics;
};

}  // namespace ak