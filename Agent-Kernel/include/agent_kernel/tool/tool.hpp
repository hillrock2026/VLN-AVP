// ============================================================
// Agent Kernel - Tool Root Object (Tool boundary)
// ============================================================
// P1-IS006 Rev2 Chapters 22-23 - the canonical Tool root.
//
// Tool is the sole lifecycle authority (TOL-017), the sole
// operational-state authority (TOL-030, TOL-094), and owns
// identity, capability storage, registration state, Provider
// ownership, Tool Services, and Tool Extensions (TOL-051).
//
// Construction establishes ToolLifecycleState = kInitializing
// and ToolOperationalState = kUninitialized (TOL-020). The
// ToolId is fixed at construction (TOL-013, TOL-081) and
// ToolConfiguration is immutable after construction
// (TOL-112); an empty name throws std::invalid_argument.
//
// One Tool root SHALL represent exactly one Tool Object and
// exactly one ToolId (TOL-081); no public operation registers,
// enumerates, or addresses a second Tool identity.
//
// NON-responsibilities:
// - Tool SHALL NOT own Runtime execution, scheduling,
//   capability resolution, event publication, or concurrency
//   (TOL-005, TOL-074).
// ============================================================

#pragma once

#include <memory>
#include <string>
#include <utility>

#include <agent_kernel/tool/capability_contract.hpp>
#include <agent_kernel/tool/i_tool_extension.hpp>
#include <agent_kernel/tool/i_tool_provider.hpp>
#include <agent_kernel/tool/tool_capability.hpp>
#include <agent_kernel/tool/tool_identity.hpp>
#include <agent_kernel/tool/tool_result.hpp>
#include <agent_kernel/tool/tool_services.hpp>
#include <agent_kernel/tool/tool_state.hpp>

namespace ak::tool {

// Tool configuration (Chapter 23). Immutable after Tool
// construction (TOL-112); the constructor rejects an empty
// `name` by throwing std::invalid_argument.
struct ToolConfiguration {
    std::string name;
    std::string version;
    std::string description;
};

// Invocation preparation request (Chapter 21). A malformed
// request (empty request_id or empty payload) is rejected
// deterministically with kRejected.
struct InvocationRequest {
    CapabilityId capability_id;
    std::string request_id;
    std::string payload;
};

// The canonical Tool root (Chapter 22.1).
class Tool final {
public:
    Tool(ToolId id, ToolConfiguration configuration);

    Tool(const Tool&) = delete;
    Tool& operator=(const Tool&) = delete;
    Tool(Tool&&) = delete;
    Tool& operator=(Tool&&) = delete;

    ~Tool();

    // -- identity / state --
    [[nodiscard]] const ToolId& Id() const noexcept;
    [[nodiscard]] ToolLifecycleState LifecycleState() const noexcept;
    [[nodiscard]] ToolOperationalState OperationalState() const noexcept;

    // -- lifecycle (Chapters 9-10) --
    [[nodiscard]] ToolLifecycleResult Register();
    [[nodiscard]] ToolLifecycleResult Activate();
    [[nodiscard]] ToolLifecycleResult Suspend();
    [[nodiscard]] ToolLifecycleResult Resume();
    [[nodiscard]] ToolLifecycleResult Retire();
    [[nodiscard]] ToolLifecycleResult FinalizeRetirement();

    // -- Tool Services (owned by the root; TOL-052/053) --
    [[nodiscard]] IToolDiscoveryService& Discovery() noexcept;
    [[nodiscard]] IToolRegistrationService& Registration() noexcept;
    [[nodiscard]] IToolCapabilityService& Capabilities() noexcept;
    [[nodiscard]] IToolAvailabilityService& Availability() noexcept;
    [[nodiscard]] IToolPermissionService& Permissions() noexcept;
    [[nodiscard]] IToolProviderService& Providers() noexcept;
    [[nodiscard]] IToolInvocationPreparationService& InvocationPreparation() noexcept;
    [[nodiscard]] IToolExtensionService& Extensions() noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace ak::tool