// ============================================================
// Agent Kernel - Tool Result Types (Tool boundary)
// ============================================================
// P1-IS006 Rev2 Chapters 10, 17, 18, 21 and 28 - canonical
// result envelopes and status types.
//
// Every public operation returns either a typed success value
// or a typed deterministic failure result (TOL-091). A failure
// result SHALL NOT invent a payload value: on failure, optional
// payload members SHALL be empty and `provider` SHALL be
// nullptr.
//
// Exceptions SHALL NOT be used as the normal Tool control-flow
// mechanism; the only exception-based paths are construction
// failure (TOL-111) and configuration validation (TOL-112).
//
// NON-responsibilities:
// - No result type references Runtime, Scheduler, Executor,
//   CapabilityResolver, EventBus, Workflow, or Task.
// ============================================================

#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include <agent_kernel/tool/capability_contract.hpp>
#include <agent_kernel/tool/tool_capability.hpp>
#include <agent_kernel/tool/tool_identity.hpp>
#include <agent_kernel/tool/tool_state.hpp>

namespace ak::tool {

class IToolProvider;  // non-owning view target of ProviderViewResult

// The canonical generic Tool result status (Chapter 28.1).
enum class ToolResultStatus : std::uint8_t {
    kSuccess = 0,
    kInvalidArgument,
    kNotFound,
    kAlreadyExists,
    kInvalidState,
    kUnavailable,
    kRejected,
    kConflict
};

// Capability result envelope.
struct ToolCapabilityResult {
    ToolResultStatus status = ToolResultStatus::kUnavailable;
    std::optional<ToolCapability> capability = std::nullopt;
    std::string message;
};

// Capability contract result envelope.
struct CapabilityContractResult {
    ToolResultStatus status = ToolResultStatus::kUnavailable;
    std::optional<CapabilityContract> contract = std::nullopt;
    std::string message;
};

// Discovery result envelope.
struct ToolDiscoveryResult {
    ToolResultStatus status = ToolResultStatus::kUnavailable;
    std::vector<ToolCapability> capabilities;
    std::string message;
};

// Provider operation result envelope.
struct ProviderResult {
    ToolResultStatus status = ToolResultStatus::kUnavailable;
    std::optional<ProviderId> provider_id = std::nullopt;
    std::string message;
};

// Provider view result envelope (non-owning; valid only while
// the Provider remains registered, TOL-100).
struct ProviderViewResult {
    ToolResultStatus status = ToolResultStatus::kUnavailable;
    IToolProvider* provider = nullptr;  // non-owning view
    std::string message;
};

// Extension operation result envelope.
struct ExtensionResult {
    ToolResultStatus status = ToolResultStatus::kUnavailable;
    std::string message;
};

// Lifecycle result status (Chapter 10).
enum class ToolLifecycleResultStatus : std::uint8_t {
    kSuccess = 0,
    kInvalidState,
    kUnavailable,
    kRejected
};

// The canonical lifecycle result (Chapter 10). Contains the
// Tool state observed at the operation linearization point
// (TOL-028).
struct ToolLifecycleResult {
    ToolLifecycleResultStatus status = ToolLifecycleResultStatus::kInvalidState;
    ToolLifecycleState state = ToolLifecycleState::kInitializing;
    std::string message;

    [[nodiscard]] bool Succeeded() const noexcept {
        return status == ToolLifecycleResultStatus::kSuccess;
    }
};

// Capability availability result (Chapter 17).
struct CapabilityAvailabilityResult {
    ToolResultStatus status = ToolResultStatus::kUnavailable;
    CapabilityAvailability availability = CapabilityAvailability::kUnavailable;
    std::string message;
};

// Tool availability result (Chapter 17).
struct ToolAvailabilityResult {
    ToolResultStatus status = ToolResultStatus::kUnavailable;
    bool available = false;
    std::string message;
};

// Permission context (Chapter 18).
struct PermissionContext {
    std::string agent_context;  // Agent-provided context identifier
    std::string policy_scope;   // Tool-owned policy scope
};

// Permission decision (Chapter 18).
enum class PermissionDecision : std::uint8_t {
    kAllowed = 0,
    kDenied,
    kIndeterminate
};

// Permission result (Chapter 18).
struct PermissionResult {
    ToolResultStatus status = ToolResultStatus::kUnavailable;
    PermissionDecision decision = PermissionDecision::kIndeterminate;
    std::string message;
};

// Invocation preparation status (Chapter 21).
enum class InvocationPreparationStatus : std::uint8_t {
    kPrepared = 0,
    kUnavailable,
    kRejected,
    kInvalidCapability,
    kNotFound
};

// Invocation preparation result (Chapter 21). The
// invocation_token identifies the prepared Tool-level
// invocation; it SHALL NOT be interpreted as a Runtime Task ID
// or Runtime execution handle (TOL-050).
struct InvocationPreparationResult {
    InvocationPreparationStatus status = InvocationPreparationStatus::kRejected;
    CapabilityId capability_id;
    ProviderId provider_id;
    std::string invocation_token;
    std::string message;
};

}  // namespace ak::tool