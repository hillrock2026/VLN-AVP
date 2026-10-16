// ============================================================
// Agent Kernel - Tool Services (Tool boundary)
// ============================================================
// P1-IS006 Rev2 Chapters 15-21 - canonical Tool Service
// interfaces.
//
// All Tool Service references returned by the Tool root refer
// to services owned by the Tool root (TOL-052) and remain
// valid for the lifetime of the owning Tool root (TOL-053).
// After kRetired, every Tool Service operation returns the
// deterministic refusal result (kUnavailable) with no side
// effects (TOL-088).
//
// Every Tool Service SHALL enforce the lifecycle/availability
// matrix (Chapter 31) before performing its operation
// (TOL-077); a service SHALL NOT infer availability from
// another service.
//
// NON-responsibilities:
// - Discovery SHALL NOT enumerate other Tool roots (TOL-083):
//   no ListTools() or equivalent multi-Tool surface exists.
// - Provider Service SHALL NOT resolve Runtime capabilities
//   (TOL-048).
// ============================================================

#pragma once

#include <memory>
#include <string>
#include <vector>

#include <agent_kernel/tool/i_tool_provider.hpp>
#include <agent_kernel/tool/tool_capability.hpp>
#include <agent_kernel/tool/tool_identity.hpp>
#include <agent_kernel/tool/tool_result.hpp>

namespace ak::tool {

struct InvocationRequest;  // defined in tool.hpp (TOL-090)

// Tool registration service (Chapter 15.4).
// Register() is equivalent to the root lifecycle Register()
// and enforces the same transition and duplicate rules
// (TOL-021, TOL-042, TOL-065).
class IToolRegistrationService {
public:
    virtual ~IToolRegistrationService() = default;

    [[nodiscard]] virtual ToolLifecycleResult Register() = 0;

    [[nodiscard]] virtual bool IsRegistered() const noexcept = 0;
};

// Tool discovery service (Chapter 16).
class IToolDiscoveryService {
public:
    virtual ~IToolDiscoveryService() = default;

    [[nodiscard]] virtual ToolDiscoveryResult ListCapabilities() const = 0;

    [[nodiscard]] virtual ToolCapabilityResult FindCapability(
        const CapabilityId& capability_id) const = 0;
};

// Tool availability service (Chapter 17).
class IToolAvailabilityService {
public:
    virtual ~IToolAvailabilityService() = default;

    [[nodiscard]] virtual CapabilityAvailabilityResult GetAvailability(
        const CapabilityId& capability_id) const = 0;

    [[nodiscard]] virtual ToolAvailabilityResult IsToolAvailable() const noexcept = 0;
};

// Tool permission service (Chapter 18).
class IToolPermissionService {
public:
    virtual ~IToolPermissionService() = default;

    [[nodiscard]] virtual PermissionResult Check(
        const CapabilityId& capability_id,
        const PermissionContext& context) const = 0;
};

// Tool capability service (Chapter 19).
class IToolCapabilityService {
public:
    virtual ~IToolCapabilityService() = default;

    [[nodiscard]] virtual ToolCapabilityResult Get(
        const CapabilityId& capability_id) const = 0;

    [[nodiscard]] virtual CapabilityContractResult GetContract(
        const CapabilityId& capability_id) const = 0;

    [[nodiscard]] virtual ToolCapabilityResult RegisterCapability(
        ToolCapability capability) = 0;

    [[nodiscard]] virtual ToolCapabilityResult ReplaceCapability(
        ToolCapability capability) = 0;
};

// Tool Provider service (Chapter 20).
class IToolProviderService {
public:
    virtual ~IToolProviderService() = default;

    [[nodiscard]] virtual ProviderResult Register(
        std::unique_ptr<IToolProvider> provider) = 0;

    [[nodiscard]] virtual ProviderResult Unregister(
        const ProviderId& provider_id) = 0;

    [[nodiscard]] virtual ProviderResult ProviderFor(
        const CapabilityId& capability_id) const = 0;

    [[nodiscard]] virtual ProviderViewResult GetProvider(
        const ProviderId& provider_id) const = 0;
};

// Tool invocation preparation service (Chapter 21).
class IToolInvocationPreparationService {
public:
    virtual ~IToolInvocationPreparationService() = default;

    [[nodiscard]] virtual InvocationPreparationResult PrepareInvocation(
        const InvocationRequest& request) const = 0;
};

}  // namespace ak::tool