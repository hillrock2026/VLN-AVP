// ============================================================
// Agent Kernel - Tool root implementation (Tool boundary)
// ============================================================
// P1-IS006 Rev2 Chapters 9-32 implementation.
//
// Concurrency contract (TOL-063/104/105): one Tool-owned
// synchronization domain (Impl::mutex) serializes ALL public
// Tool operations. Provider/extension user callbacks are
// invoked OUTSIDE the domain (TOL-106); re-entrant calls from
// a callback are rejected deterministically with kRejected.
//
// The retirement race (TOL-107) is resolved by snapshot
// capture under the domain, callback execution outside the
// domain, and snapshot re-validation before commit.
//
// NON-responsibilities:
// - This boundary performs no Runtime action; no Runtime,
//   Scheduler, Executor, CapabilityResolver, EventBus,
//   Workflow, or Task type is referenced.
// ============================================================

#include <agent_kernel/tool/tool.hpp>

#include <algorithm>
#include <cctype>
#include <condition_variable>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace ak::tool {
namespace {

// ------------------------------------------------------------
// Re-entrancy guard (TOL-106)
// ------------------------------------------------------------
// User callbacks run outside the synchronization domain. A
// callback that re-enters the same Tool root is rejected
// deterministically with kRejected (no deadlock).
thread_local bool g_in_callback = false;

class CallbackGuard {
public:
    CallbackGuard() noexcept { g_in_callback = true; }
    ~CallbackGuard() { g_in_callback = false; }
    CallbackGuard(const CallbackGuard&) = delete;
    CallbackGuard& operator=(const CallbackGuard&) = delete;
};

bool IsWhitespaceOnly(const std::string& value) {
    return std::all_of(value.begin(), value.end(),
                       [](unsigned char c) { return std::isspace(c) != 0; });
}

// ------------------------------------------------------------
// Constraint predicate (TOL-095)
// ------------------------------------------------------------
// A capability is constrained when a Tool-owned condition
// (CapabilityAvailability or CapabilityConstraintSet) on the
// published ToolCapability constrains it.
bool IsConstrained(const ToolCapability& capability) {
    return capability.availability == CapabilityAvailability::kConstrained ||
           capability.availability == CapabilityAvailability::kUnavailable ||
           capability.constraints.constrained;
}

// ------------------------------------------------------------
// Lifecycle/availability matrix gates (Chapter 31, TOL-077)
// ------------------------------------------------------------
enum class OperationAvailability { kAvailable, kUnavailable };

OperationAvailability DiscoveryAvailability(ToolLifecycleState state) {
    switch (state) {
        case ToolLifecycleState::kRegistered:
        case ToolLifecycleState::kAvailable:
        case ToolLifecycleState::kSuspended:
        case ToolLifecycleState::kRetiring:
            return OperationAvailability::kAvailable;
        default:
            return OperationAvailability::kUnavailable;
    }
}

OperationAvailability CapabilityReadAvailability(ToolLifecycleState state) {
    switch (state) {
        case ToolLifecycleState::kRegistered:
        case ToolLifecycleState::kAvailable:
        case ToolLifecycleState::kRetiring:
            return OperationAvailability::kAvailable;
        default:
            return OperationAvailability::kUnavailable;
    }
}

OperationAvailability CapabilityMutationAvailability(ToolLifecycleState state) {
    switch (state) {
        case ToolLifecycleState::kRegistered:
        case ToolLifecycleState::kAvailable:
            return OperationAvailability::kAvailable;
        default:
            return OperationAvailability::kUnavailable;
    }
}

OperationAvailability AvailabilityQueryAvailability(ToolLifecycleState state) {
    return DiscoveryAvailability(state);
}

OperationAvailability PermissionQueryAvailability(ToolLifecycleState state) {
    return CapabilityReadAvailability(state);
}

OperationAvailability ProviderReadAvailability(ToolLifecycleState state) {
    return DiscoveryAvailability(state);
}

OperationAvailability ProviderMutationAvailability(ToolLifecycleState state) {
    return CapabilityMutationAvailability(state);
}

OperationAvailability InvocationPreparationAvailability(ToolLifecycleState state) {
    return state == ToolLifecycleState::kAvailable
               ? OperationAvailability::kAvailable
               : OperationAvailability::kUnavailable;
}

bool IsPostRetired(ToolLifecycleState state) {
    return state == ToolLifecycleState::kRetired;
}

// ------------------------------------------------------------
// Deterministic result helpers
// ------------------------------------------------------------
ToolLifecycleResult MakeLifecycleResult(ToolLifecycleResultStatus status,
                                        ToolLifecycleState state,
                                        std::string message) {
    return ToolLifecycleResult{status, state, std::move(message)};
}

// Deterministic non-payload placeholder for the non-optional
// ProviderId member of InvocationPreparationResult on failure
// paths where no Provider is in scope. The capability_id
// member echoes the caller's request capability identity.
const char* kUnresolvedProviderIdValue = "<unresolved-provider>";

ProviderId UnresolvedProvider() {
    static const ProviderId unresolved{std::string(kUnresolvedProviderIdValue)};
    return unresolved;
}

InvocationPreparationResult MakePreparation(InvocationPreparationStatus status,
                                            const CapabilityId& capability_id,
                                            const ProviderId& provider_id,
                                            std::string token,
                                            std::string message) {
    return InvocationPreparationResult{status, capability_id, provider_id,
                                       std::move(token), std::move(message)};
}

// ------------------------------------------------------------
// CapabilityContract derivation (Chapter 13)
// ------------------------------------------------------------
// The Tool-owned permission information is derived
// deterministically from the published ToolCapability:
// required_permissions mirror the Tool-owned constraint
// conditions and policy_scope mirrors the Tool-owned category.
// compatibility mirrors the Tool-owned version information.
CapabilityContract MakeContract(const ToolCapability& capability) {
    PermissionContract permissions;
    permissions.required_permissions = capability.constraints.constraints;
    permissions.policy_scope = capability.category;
    return CapabilityContract(capability.id, capability.input,
                              capability.output, capability.constraints,
                              capability.metadata, capability.availability,
                              permissions, capability.provider,
                              capability.version);
}

}  // namespace

// Tool-owned root state (defined below in this TU); the service
// implementations reference it through this forward declaration.
struct ToolState;

// ------------------------------------------------------------
// Service implementations (owned by the Tool root, TOL-052)
// ------------------------------------------------------------

class RegistrationService final : public IToolRegistrationService {
public:
    explicit RegistrationService(ToolState& state) : state_(state) {}

    ToolLifecycleResult Register() override;
    bool IsRegistered() const noexcept override;

private:
    ToolState& state_;
};

class DiscoveryService final : public IToolDiscoveryService {
public:
    explicit DiscoveryService(ToolState& state) : state_(state) {}

    ToolDiscoveryResult ListCapabilities() const override;
    ToolCapabilityResult FindCapability(const CapabilityId& capability_id) const override;

private:
    ToolState& state_;
};

class CapabilityService final : public IToolCapabilityService {
public:
    explicit CapabilityService(ToolState& state) : state_(state) {}

    ToolCapabilityResult Get(const CapabilityId& capability_id) const override;
    CapabilityContractResult GetContract(const CapabilityId& capability_id) const override;
    ToolCapabilityResult RegisterCapability(ToolCapability capability) override;
    ToolCapabilityResult ReplaceCapability(ToolCapability capability) override;

private:
    ToolState& state_;
};

class AvailabilityService final : public IToolAvailabilityService {
public:
    explicit AvailabilityService(ToolState& state) : state_(state) {}

    CapabilityAvailabilityResult GetAvailability(
        const CapabilityId& capability_id) const override;
    ToolAvailabilityResult IsToolAvailable() const noexcept override;

private:
    ToolState& state_;
};

class PermissionService final : public IToolPermissionService {
public:
    explicit PermissionService(ToolState& state) : state_(state) {}

    PermissionResult Check(const CapabilityId& capability_id,
                           const PermissionContext& context) const override;

private:
    ToolState& state_;
};

class ProviderService final : public IToolProviderService {
public:
    explicit ProviderService(ToolState& state) : state_(state) {}

    ProviderResult Register(std::unique_ptr<IToolProvider> provider) override;
    ProviderResult Unregister(const ProviderId& provider_id) override;
    ProviderResult ProviderFor(const CapabilityId& capability_id) const override;
    ProviderViewResult GetProvider(const ProviderId& provider_id) const override;

private:
    ToolState& state_;
};

class InvocationPreparationService final : public IToolInvocationPreparationService {
public:
    explicit InvocationPreparationService(ToolState& state) : state_(state) {}

    InvocationPreparationResult PrepareInvocation(
        const InvocationRequest& request) const override;

private:
    ToolState& state_;
};

class ExtensionService final : public IToolExtensionService {
public:
    explicit ExtensionService(ToolState& state) : state_(state) {}

    ExtensionResult RegisterExtension(std::unique_ptr<IToolExtension> extension) override;
    ExtensionResult UnregisterExtension(const std::string& name) override;
    bool IsAttached(const std::string& name) const noexcept override;

private:
    ToolState& state_;
};

class ExtensionContext final : public IToolExtensionContext {
public:
    explicit ExtensionContext(ToolState& state) : state_(state) {}

    const ToolId& Id() const noexcept override;
    ToolLifecycleState LifecycleState() const noexcept override;
    ToolOperationalState OperationalState() const noexcept override;
    IToolCapabilityService& Capabilities() noexcept override;
    IToolProviderService& Providers() noexcept override;

private:
    ToolState& state_;
};

// ------------------------------------------------------------
// Tool root state (TOL-051)
// ------------------------------------------------------------
struct ToolState {
    ToolState(ToolId id_value, ToolConfiguration configuration_value)
        : id(std::move(id_value)),
          configuration(std::move(configuration_value)),
          registration(*this),
          discovery(*this),
          capabilities(*this),
          availability(*this),
          permissions(*this),
          providers(*this),
          invocation_preparation(*this),
          extensions(*this),
          extension_context(*this) {
        // TOL-112: configuration validation (construction
        // failure is the only exception-based path besides
        // identity construction, TOL-111).
        if (configuration.name.empty() || IsWhitespaceOnly(configuration.name)) {
            throw std::invalid_argument(
                "ToolConfiguration.name must be non-empty and contain at "
                "least one non-whitespace character (TOL-112)");
        }
    }

    ~ToolState();

    // -- immutable identity / configuration (TOL-013, TOL-112) --
    const ToolId id;
    const ToolConfiguration configuration;

    // -- the single Tool-owned synchronization domain (TOL-063) --
    std::mutex mutex;
    std::condition_variable callback_cv;
    std::size_t in_flight_callbacks = 0;

    // -- lifecycle / operational state (TOL-029, TOL-030) --
    ToolLifecycleState lifecycle_state = ToolLifecycleState::kInitializing;
    ToolOperationalState operational_state = ToolOperationalState::kUninitialized;

    // -- Tool-owned storage --
    std::vector<ToolCapability> capability_storage;
    struct ProviderEntry {
        ProviderId id;
        std::unique_ptr<IToolProvider> provider;
    };
    std::vector<ProviderEntry> provider_storage;
    struct ExtensionEntry {
        std::string name;
        std::unique_ptr<IToolExtension> extension;
        bool attached = false;
    };
    std::vector<ExtensionEntry> extension_storage;

    // -- Tool-owned services (TOL-052/053) --
    RegistrationService registration;
    DiscoveryService discovery;
    CapabilityService capabilities;
    AvailabilityService availability;
    PermissionService permissions;
    ProviderService providers;
    InvocationPreparationService invocation_preparation;
    ExtensionService extensions;
    ExtensionContext extension_context;

    // -- shared helpers (caller holds the domain) --
    bool AnyCapabilityConstrained() const {
        return std::any_of(capability_storage.begin(), capability_storage.end(),
                           [](const ToolCapability& capability) {
                               return IsConstrained(capability);
                           });
    }

    // Restricted entry/exit (TOL-095, TOL-096): re-evaluated at
    // every Tool-owned capability and Provider mutation.
    void ReevaluateRestricted() {
        if (lifecycle_state == ToolLifecycleState::kAvailable) {
            operational_state = AnyCapabilityConstrained()
                                    ? ToolOperationalState::kRestricted
                                    : ToolOperationalState::kAvailable;
        }
    }

    const ToolCapability* FindCapability(const CapabilityId& capability_id) const {
        const auto it = std::find_if(
            capability_storage.begin(), capability_storage.end(),
            [&capability_id](const ToolCapability& capability) {
                return capability.id == capability_id;
            });
        return it == capability_storage.end() ? nullptr : &(*it);
    }

    ProviderEntry* FindProviderEntry(const ProviderId& provider_id) {
        const auto it = std::find_if(
            provider_storage.begin(), provider_storage.end(),
            [&provider_id](const ProviderEntry& entry) {
                return entry.id == provider_id;
            });
        return it == provider_storage.end() ? nullptr : &(*it);
    }

    const ProviderEntry* FindProviderEntry(const ProviderId& provider_id) const {
        const auto it = std::find_if(
            provider_storage.begin(), provider_storage.end(),
            [&provider_id](const ProviderEntry& entry) {
                return entry.id == provider_id;
            });
        return it == provider_storage.end() ? nullptr : &(*it);
    }

    IToolProvider* FindProvider(const ProviderId& provider_id) {
        ProviderEntry* entry = FindProviderEntry(provider_id);
        return entry == nullptr ? nullptr : entry->provider.get();
    }

    ExtensionEntry* FindExtension(const std::string& name) {
        const auto it = std::find_if(
            extension_storage.begin(), extension_storage.end(),
            [&name](const ExtensionEntry& entry) { return entry.name == name; });
        return it == extension_storage.end() ? nullptr : &(*it);
    }

    bool HasExtension(const std::string& name) const {
        return std::any_of(extension_storage.begin(), extension_storage.end(),
                           [&name](const ExtensionEntry& entry) {
                               return entry.name == name;
                           });
    }
};

struct Tool::Impl : ToolState {
    Impl(ToolId id_value, ToolConfiguration configuration_value)
        : ToolState(std::move(id_value), std::move(configuration_value)) {}
};

ToolState::~ToolState() {
    // Wait for in-flight Provider callbacks before destroying
    // Provider storage (TOL-100: the Tool root controls Provider
    // lifetime and destruction).
    std::unique_lock<std::mutex> lock(mutex);
    callback_cv.wait(lock, [this] { return in_flight_callbacks == 0; });
    lock.unlock();
}

// ------------------------------------------------------------
// RegistrationService
// ------------------------------------------------------------
ToolLifecycleResult RegistrationService::Register() {
    if (g_in_callback) {
        std::lock_guard<std::mutex> lock(state_.mutex);
        return MakeLifecycleResult(ToolLifecycleResultStatus::kRejected,
                                   state_.lifecycle_state,
                                   "re-entrant Tool call rejected (TOL-106)");
    }
    std::lock_guard<std::mutex> lock(state_.mutex);
    if (state_.lifecycle_state != ToolLifecycleState::kInitializing) {
        return MakeLifecycleResult(ToolLifecycleResultStatus::kInvalidState,
                                   state_.lifecycle_state,
                                   "Register requires kInitializing (TOL-021, TOL-042)");
    }
    state_.lifecycle_state = ToolLifecycleState::kRegistered;
    state_.operational_state = ToolOperationalState::kRegistered;
    return MakeLifecycleResult(ToolLifecycleResultStatus::kSuccess,
                               state_.lifecycle_state, "");
}

bool RegistrationService::IsRegistered() const noexcept {
    std::lock_guard<std::mutex> lock(state_.mutex);
    return state_.lifecycle_state != ToolLifecycleState::kInitializing;
}

// ------------------------------------------------------------
// DiscoveryService
// ------------------------------------------------------------
ToolDiscoveryResult DiscoveryService::ListCapabilities() const {
    if (g_in_callback) {
        return {ToolResultStatus::kRejected, {},
                "re-entrant Tool call rejected (TOL-106)"};
    }
    std::lock_guard<std::mutex> lock(state_.mutex);
    if (DiscoveryAvailability(state_.lifecycle_state) !=
        OperationAvailability::kAvailable) {
        return {ToolResultStatus::kUnavailable, {},
                "discovery unavailable in current lifecycle state (TOL-092)"};
    }
    return {ToolResultStatus::kSuccess, state_.capability_storage, ""};
}

ToolCapabilityResult DiscoveryService::FindCapability(
    const CapabilityId& capability_id) const {
    if (g_in_callback) {
        return {ToolResultStatus::kRejected, std::nullopt,
                "re-entrant Tool call rejected (TOL-106)"};
    }
    std::lock_guard<std::mutex> lock(state_.mutex);
    if (DiscoveryAvailability(state_.lifecycle_state) !=
        OperationAvailability::kAvailable) {
        return {ToolResultStatus::kUnavailable, std::nullopt,
                "discovery unavailable in current lifecycle state (TOL-092)"};
    }
    const ToolCapability* found = state_.FindCapability(capability_id);
    if (found == nullptr) {
        return {ToolResultStatus::kNotFound, std::nullopt,
                "unknown capability (TOL-083, TOL-092)"};
    }
    return {ToolResultStatus::kSuccess, *found, ""};
}

// ------------------------------------------------------------
// CapabilityService
// ------------------------------------------------------------
ToolCapabilityResult CapabilityService::Get(
    const CapabilityId& capability_id) const {
    if (g_in_callback) {
        return {ToolResultStatus::kRejected, std::nullopt,
                "re-entrant Tool call rejected (TOL-106)"};
    }
    std::lock_guard<std::mutex> lock(state_.mutex);
    if (CapabilityReadAvailability(state_.lifecycle_state) !=
        OperationAvailability::kAvailable) {
        return {ToolResultStatus::kUnavailable, std::nullopt,
                "capability lookup unavailable in current lifecycle state (TOL-092)"};
    }
    const ToolCapability* found = state_.FindCapability(capability_id);
    if (found == nullptr) {
        return {ToolResultStatus::kNotFound, std::nullopt,
                "unknown capability (TOL-092)"};
    }
    return {ToolResultStatus::kSuccess, *found, ""};
}

CapabilityContractResult CapabilityService::GetContract(
    const CapabilityId& capability_id) const {
    if (g_in_callback) {
        return {ToolResultStatus::kRejected, std::nullopt,
                "re-entrant Tool call rejected (TOL-106)"};
    }
    std::lock_guard<std::mutex> lock(state_.mutex);
    if (CapabilityReadAvailability(state_.lifecycle_state) !=
        OperationAvailability::kAvailable) {
        return {ToolResultStatus::kUnavailable, std::nullopt,
                "capability lookup unavailable in current lifecycle state (TOL-092)"};
    }
    const ToolCapability* found = state_.FindCapability(capability_id);
    if (found == nullptr) {
        return {ToolResultStatus::kNotFound, std::nullopt,
                "unknown capability (TOL-092)"};
    }
    return {ToolResultStatus::kSuccess, MakeContract(*found), ""};
}

ToolCapabilityResult CapabilityService::RegisterCapability(
    ToolCapability capability) {
    if (g_in_callback) {
        return {ToolResultStatus::kRejected, std::nullopt,
                "re-entrant Tool call rejected (TOL-106)"};
    }
    std::lock_guard<std::mutex> lock(state_.mutex);
    if (CapabilityMutationAvailability(state_.lifecycle_state) !=
        OperationAvailability::kAvailable) {
        return {ToolResultStatus::kUnavailable, std::nullopt,
                "capability mutation unavailable in current lifecycle state (TOL-092)"};
    }
    if (state_.FindCapability(capability.id) != nullptr) {
        return {ToolResultStatus::kAlreadyExists, std::nullopt,
                "duplicate capability id (TOL-042)"};
    }
    state_.capability_storage.push_back(capability);
    state_.ReevaluateRestricted();
    return {ToolResultStatus::kSuccess, capability, ""};
}

ToolCapabilityResult CapabilityService::ReplaceCapability(
    ToolCapability capability) {
    if (g_in_callback) {
        return {ToolResultStatus::kRejected, std::nullopt,
                "re-entrant Tool call rejected (TOL-106)"};
    }
    std::lock_guard<std::mutex> lock(state_.mutex);
    if (CapabilityMutationAvailability(state_.lifecycle_state) !=
        OperationAvailability::kAvailable) {
        return {ToolResultStatus::kUnavailable, std::nullopt,
                "capability mutation unavailable in current lifecycle state (TOL-092)"};
    }
    const auto it = std::find_if(
        state_.capability_storage.begin(), state_.capability_storage.end(),
        [&capability](const ToolCapability& stored) {
            return stored.id == capability.id;
        });
    if (it == state_.capability_storage.end()) {
        return {ToolResultStatus::kNotFound, std::nullopt,
                "unknown capability (TOL-092)"};
    }
    // Immutability (TOL-034): modification replaces the
    // published value rather than mutating a value already
    // returned to a consumer.
    *it = capability;
    state_.ReevaluateRestricted();
    return {ToolResultStatus::kSuccess, capability, ""};
}

// ------------------------------------------------------------
// AvailabilityService
// ------------------------------------------------------------
CapabilityAvailabilityResult AvailabilityService::GetAvailability(
    const CapabilityId& capability_id) const {
    if (g_in_callback) {
        return {ToolResultStatus::kRejected, CapabilityAvailability::kUnavailable,
                "re-entrant Tool call rejected (TOL-106)"};
    }
    std::lock_guard<std::mutex> lock(state_.mutex);
    if (AvailabilityQueryAvailability(state_.lifecycle_state) !=
        OperationAvailability::kAvailable) {
        return {ToolResultStatus::kUnavailable, CapabilityAvailability::kUnavailable,
                "availability query unavailable in current lifecycle state (TOL-092)"};
    }
    const ToolCapability* found = state_.FindCapability(capability_id);
    if (found == nullptr) {
        return {ToolResultStatus::kNotFound, CapabilityAvailability::kUnavailable,
                "unknown capability (TOL-092)"};
    }
    return {ToolResultStatus::kSuccess, found->availability, ""};
}

ToolAvailabilityResult AvailabilityService::IsToolAvailable() const noexcept {
    if (g_in_callback) {
        return {ToolResultStatus::kRejected, false,
                "re-entrant Tool call rejected (TOL-106)"};
    }
    std::lock_guard<std::mutex> lock(state_.mutex);
    if (AvailabilityQueryAvailability(state_.lifecycle_state) !=
        OperationAvailability::kAvailable) {
        return {ToolResultStatus::kUnavailable, false,
                "availability query unavailable in current lifecycle state (TOL-092)"};
    }
    const bool available =
        state_.lifecycle_state == ToolLifecycleState::kAvailable;
    return {ToolResultStatus::kSuccess, available, ""};
}

// ------------------------------------------------------------
// PermissionService
// ------------------------------------------------------------
PermissionResult PermissionService::Check(
    const CapabilityId& capability_id,
    const PermissionContext& context) const {
    if (g_in_callback) {
        return {ToolResultStatus::kRejected, PermissionDecision::kIndeterminate,
                "re-entrant Tool call rejected (TOL-106)"};
    }
    std::lock_guard<std::mutex> lock(state_.mutex);
    if (PermissionQueryAvailability(state_.lifecycle_state) !=
        OperationAvailability::kAvailable) {
        return {ToolResultStatus::kUnavailable, PermissionDecision::kIndeterminate,
                "permission query unavailable in current lifecycle state (TOL-092)"};
    }
    const ToolCapability* found = state_.FindCapability(capability_id);
    if (found == nullptr) {
        return {ToolResultStatus::kNotFound, PermissionDecision::kIndeterminate,
                "unknown capability (TOL-092)"};
    }
    // Deterministic Tool-owned permission decision (Chapter 18,
    // TOL-046). The Agent-provided context identifier is not a
    // Tool-owned authorization authority; the decision uses
    // Tool-owned capability information only.
    PermissionDecision decision = PermissionDecision::kAllowed;
    std::string message = "permission granted";
    if (IsConstrained(*found)) {
        decision = PermissionDecision::kDenied;
        message = "capability is constrained by a Tool-owned condition";
    } else if (context.policy_scope.empty() && !found->category.empty()) {
        decision = PermissionDecision::kIndeterminate;
        message = "policy scope not supplied";
    } else if (!context.policy_scope.empty() && found->category.empty()) {
        decision = PermissionDecision::kAllowed;
        message = "no Tool-owned scope restriction";
    } else if (context.policy_scope != found->category) {
        decision = PermissionDecision::kDenied;
        message = "policy scope mismatch";
    }
    return {ToolResultStatus::kSuccess, decision, message};
}// ------------------------------------------------------------
// ProviderService
// ------------------------------------------------------------
ProviderResult ProviderService::Register(
    std::unique_ptr<IToolProvider> provider) {
    if (g_in_callback) {
        return {ToolResultStatus::kRejected, std::nullopt,
                "re-entrant Tool call rejected (TOL-106)"};
    }
    if (!provider) {
        return {ToolResultStatus::kRejected, std::nullopt,
                "null provider rejected"};
    }
    // Id() is user code: invoked outside the synchronization
    // domain (TOL-106).
    const ProviderId provider_id = provider->Id();
    std::unique_ptr<IToolProvider> staged = std::move(provider);
    std::vector<ToolCapability> described;
    {
        // Snapshot + admission under the domain (TOL-106).
        std::lock_guard<std::mutex> lock(state_.mutex);
        if (ProviderMutationAvailability(state_.lifecycle_state) !=
            OperationAvailability::kAvailable) {
            return {ToolResultStatus::kUnavailable, std::nullopt,
                    "provider mutation unavailable in current lifecycle state (TOL-092)"};
        }
        if (state_.FindProviderEntry(provider_id) != nullptr) {
            return {ToolResultStatus::kAlreadyExists, std::nullopt,
                    "duplicate provider id (TOL-042)"};
        }
    }
    // DescribeCapabilities callback outside the domain
    // (TOL-106); failures normalized to kRejected (TOL-093).
    try {
        CallbackGuard guard;
        described = staged->DescribeCapabilities();
    } catch (...) {
        return {ToolResultStatus::kRejected, std::nullopt,
                "Provider DescribeCapabilities raised; normalized to kRejected (TOL-093)"};
    }
    // Re-acquire; re-validate the snapshot; commit (TOL-106).
    {
        std::lock_guard<std::mutex> lock(state_.mutex);
        if (ProviderMutationAvailability(state_.lifecycle_state) !=
            OperationAvailability::kAvailable) {
            return {ToolResultStatus::kUnavailable, std::nullopt,
                    "tool state changed during provider registration; refused (TOL-106)"};
        }
        if (state_.FindProviderEntry(provider_id) != nullptr) {
            return {ToolResultStatus::kAlreadyExists, std::nullopt,
                    "duplicate provider id appeared during registration; refused (TOL-106)"};
        }
        for (std::size_t i = 0; i < described.size(); ++i) {
            if (state_.FindCapability(described[i].id) != nullptr) {
                return {ToolResultStatus::kAlreadyExists, std::nullopt,
                        "described capability conflicts with a registered capability (TOL-042)"};
            }
            for (std::size_t j = i + 1; j < described.size(); ++j) {
                if (described[i].id == described[j].id) {
                    return {ToolResultStatus::kRejected, std::nullopt,
                            "provider description contains duplicate capability ids"};
                }
            }
        }
        // Commit: transfer exclusive ownership (TOL-099) and
        // publish the described capabilities, binding each to
        // its registering Provider (the architectural source).
        ToolState::ProviderEntry entry{provider_id, std::move(staged)};
        state_.provider_storage.push_back(std::move(entry));
        for (auto& capability : described) {
            capability.provider = provider_id;
            state_.capability_storage.push_back(std::move(capability));
        }
        state_.ReevaluateRestricted();
    }
    return {ToolResultStatus::kSuccess, provider_id, ""};
}

ProviderResult ProviderService::Unregister(const ProviderId& provider_id) {
    if (g_in_callback) {
        return {ToolResultStatus::kRejected, std::nullopt,
                "re-entrant Tool call rejected (TOL-106)"};
    }
    std::unique_ptr<IToolProvider> removed;
    {
        std::lock_guard<std::mutex> lock(state_.mutex);
        if (ProviderMutationAvailability(state_.lifecycle_state) !=
            OperationAvailability::kAvailable) {
            return {ToolResultStatus::kUnavailable, std::nullopt,
                    "provider mutation unavailable in current lifecycle state (TOL-092)"};
        }
        auto it = std::find_if(
            state_.provider_storage.begin(), state_.provider_storage.end(),
            [&provider_id](const ToolState::ProviderEntry& entry) {
                return entry.id == provider_id;
            });
        if (it == state_.provider_storage.end()) {
            return {ToolResultStatus::kNotFound, std::nullopt,
                    "unknown provider (TOL-092)"};
        }
        removed = std::move(it->provider);
        state_.provider_storage.erase(it);
        state_.ReevaluateRestricted();
    }
    // TOL-100: wait for in-flight callbacks, then destroy the
    // unregistered Provider before returning (destruction
    // happens outside the synchronization domain, TOL-106).
    std::unique_lock<std::mutex> wait_lock(state_.mutex);
    state_.callback_cv.wait(wait_lock,
                            [this] { return state_.in_flight_callbacks == 0; });
    wait_lock.unlock();
    return {ToolResultStatus::kSuccess, provider_id, ""};
}

ProviderResult ProviderService::ProviderFor(
    const CapabilityId& capability_id) const {
    if (g_in_callback) {
        return {ToolResultStatus::kRejected, std::nullopt,
                "re-entrant Tool call rejected (TOL-106)"};
    }
    std::lock_guard<std::mutex> lock(state_.mutex);
    if (ProviderReadAvailability(state_.lifecycle_state) !=
        OperationAvailability::kAvailable) {
        return {ToolResultStatus::kUnavailable, std::nullopt,
                "provider read unavailable in current lifecycle state (TOL-092)"};
    }
    const ToolCapability* found = state_.FindCapability(capability_id);
    if (found == nullptr) {
        return {ToolResultStatus::kNotFound, std::nullopt,
                "unknown capability (TOL-092)"};
    }
    return {ToolResultStatus::kSuccess, found->provider, ""};
}

ProviderViewResult ProviderService::GetProvider(
    const ProviderId& provider_id) const {
    if (g_in_callback) {
        return {ToolResultStatus::kRejected, nullptr,
                "re-entrant Tool call rejected (TOL-106)"};
    }
    std::lock_guard<std::mutex> lock(state_.mutex);
    if (ProviderReadAvailability(state_.lifecycle_state) !=
        OperationAvailability::kAvailable) {
        return {ToolResultStatus::kUnavailable, nullptr,
                "provider read unavailable in current lifecycle state (TOL-092)"};
    }
    IToolProvider* provider = state_.FindProvider(provider_id);
    if (provider == nullptr) {
        return {ToolResultStatus::kNotFound, nullptr,
                "unknown provider (TOL-092)"};
    }
    return {ToolResultStatus::kSuccess, provider, ""};
}

// ------------------------------------------------------------
// InvocationPreparationService
// ------------------------------------------------------------
InvocationPreparationResult InvocationPreparationService::PrepareInvocation(
    const InvocationRequest& request) const {
    // Deterministic priority (TOL-092): re-entrancy, then
    // malformed request, then lifecycle gate, then capability
    // lookup, then constraint, then Provider availability.
    if (g_in_callback) {
        return MakePreparation(InvocationPreparationStatus::kRejected,
                               request.capability_id, UnresolvedProvider(), "",
                               "re-entrant Tool call rejected (TOL-106)");
    }
    if (request.request_id.empty() || request.payload.empty()) {
        return MakePreparation(InvocationPreparationStatus::kRejected,
                               request.capability_id, UnresolvedProvider(), "",
                               "malformed request: request_id and payload must be non-empty");
    }

    const CapabilityId capability_id = request.capability_id;
    ProviderId provider_id = UnresolvedProvider();
    IToolProvider* provider = nullptr;
    {
        // Snapshot capture under the domain (TOL-106).
        std::lock_guard<std::mutex> lock(state_.mutex);
        if (InvocationPreparationAvailability(state_.lifecycle_state) !=
            OperationAvailability::kAvailable) {
            return MakePreparation(InvocationPreparationStatus::kUnavailable,
                                   capability_id, UnresolvedProvider(), "",
                                   "invocation preparation unavailable in current lifecycle state (TOL-092)");
        }
        const ToolCapability* capability = state_.FindCapability(capability_id);
        if (capability == nullptr) {
            return MakePreparation(InvocationPreparationStatus::kNotFound,
                                   capability_id, UnresolvedProvider(), "",
                                   "unknown capability (TOL-092)");
        }
        if (IsConstrained(*capability)) {
            return MakePreparation(InvocationPreparationStatus::kUnavailable,
                                   capability_id, capability->provider, "",
                                   "capability is constrained (TOL-098)");
        }
        const ToolState::ProviderEntry* entry =
            state_.FindProviderEntry(capability->provider);
        if (entry == nullptr) {
            return MakePreparation(InvocationPreparationStatus::kUnavailable,
                                   capability_id, capability->provider, "",
                                   "capability provider is not registered");
        }
        provider_id = entry->id;
        provider = entry->provider.get();
        state_.in_flight_callbacks += 1;
    }

    struct InFlightGuard {
        ToolState& state;
        ~InFlightGuard() {
            std::lock_guard<std::mutex> lock(state.mutex);
            state.in_flight_callbacks -= 1;
            state.callback_cv.notify_all();
        }
    } in_flight{state_};

    // Provider callbacks outside the domain (TOL-106); failures
    // normalized to kRejected (TOL-093).
    bool provider_available = false;
    try {
        CallbackGuard guard;
        provider_available = provider->IsAvailable();
    } catch (...) {
        return MakePreparation(InvocationPreparationStatus::kRejected,
                               capability_id, provider_id, "",
                               "Provider IsAvailable raised; normalized to kRejected (TOL-093)");
    }
    if (!provider_available) {
        return MakePreparation(InvocationPreparationStatus::kRejected,
                               capability_id, provider_id, "",
                               "provider reports unavailable (TOL-092)");
    }
    InvocationPreparationResult prepared = MakePreparation(
        InvocationPreparationStatus::kRejected, capability_id, provider_id,
        "", "");
    bool callback_raised = false;
    try {
        CallbackGuard guard;
        prepared = provider->PrepareInvocation(capability_id, request);
    } catch (...) {
        callback_raised = true;
    }
    if (callback_raised) {
        return MakePreparation(InvocationPreparationStatus::kRejected,
                               capability_id, provider_id, "",
                               "Provider PrepareInvocation raised; normalized to kRejected (TOL-093)");
    }

    // Re-acquire; re-validate the snapshot; commit (TOL-106,
    // TOL-107).
    {
        std::lock_guard<std::mutex> lock(state_.mutex);
        if (InvocationPreparationAvailability(state_.lifecycle_state) !=
            OperationAvailability::kAvailable) {
            return MakePreparation(InvocationPreparationStatus::kUnavailable,
                                   capability_id, provider_id, "",
                                   "tool state changed during preparation; refused (TOL-106/107)");
        }
        const ToolCapability* current = state_.FindCapability(capability_id);
        if (current == nullptr || IsConstrained(*current)) {
            return MakePreparation(InvocationPreparationStatus::kUnavailable,
                                   capability_id, provider_id, "",
                                   "capability changed during preparation; refused (TOL-106)");
        }
        if (state_.FindProvider(provider_id) != provider) {
            return MakePreparation(InvocationPreparationStatus::kUnavailable,
                                   capability_id, provider_id, "",
                                   "provider changed during preparation; refused (TOL-106)");
        }
    }
    if (prepared.status == InvocationPreparationStatus::kPrepared) {
        return MakePreparation(InvocationPreparationStatus::kPrepared,
                               capability_id, provider_id,
                               prepared.invocation_token, prepared.message);
    }
    return MakePreparation(InvocationPreparationStatus::kRejected,
                           capability_id, provider_id, "",
                           prepared.message.empty()
                               ? "provider did not prepare invocation"
                               : prepared.message);
}

// ------------------------------------------------------------
// ExtensionService
// ------------------------------------------------------------
ExtensionResult ExtensionService::RegisterExtension(
    std::unique_ptr<IToolExtension> extension) {
    if (g_in_callback) {
        return {ToolResultStatus::kRejected,
                "re-entrant Tool call rejected (TOL-106)"};
    }
    if (!extension) {
        return {ToolResultStatus::kRejected, "null extension rejected"};
    }
    // Name() is user code: invoked outside the domain (TOL-106).
    std::string name;
    try {
        name = extension->Name();
    } catch (...) {
        return {ToolResultStatus::kRejected,
                "extension Name() raised; normalized to kRejected"};
    }
    if (name.empty()) {
        return {ToolResultStatus::kRejected,
                "extension name must be non-empty"};
    }
    std::unique_ptr<IToolExtension> staged = std::move(extension);
    {
        std::lock_guard<std::mutex> lock(state_.mutex);
        if (IsPostRetired(state_.lifecycle_state)) {
            return {ToolResultStatus::kUnavailable,
                    "extension registration unavailable after kRetired (TOL-088)"};
        }
        if (state_.HasExtension(name)) {
            return {ToolResultStatus::kAlreadyExists,
                    "duplicate extension name (TOL-103)"};
        }
    }
    // Attach callback outside the domain (TOL-106).
    bool attach_raised = false;
    try {
        CallbackGuard guard;
        staged->Attach(state_.extension_context);
    } catch (...) {
        attach_raised = true;
    }
    if (attach_raised) {
        // No state mutation on rejected attach (TOL-065,
        // TOL-103); the staged extension is destroyed here.
        return {ToolResultStatus::kRejected,
                "extension Attach raised; normalized to kRejected; no state mutation"};
    }
    ToolResultStatus rollback_status = ToolResultStatus::kSuccess;
    std::string rollback_message;
    bool rollback = false;
    {
        std::lock_guard<std::mutex> lock(state_.mutex);
        if (IsPostRetired(state_.lifecycle_state)) {
            rollback = true;
            rollback_status = ToolResultStatus::kUnavailable;
            rollback_message =
                "tool retired during attach; refused (TOL-106)";
        } else if (state_.HasExtension(name)) {
            rollback = true;
            rollback_status = ToolResultStatus::kAlreadyExists;
            rollback_message =
                "duplicate extension name appeared during attach; refused (TOL-106)";
        }
    }
    if (rollback) {
        try {
            CallbackGuard guard;
            staged->Detach(state_.extension_context);
        } catch (...) {
        }
        return {rollback_status, rollback_message};
    }
    {
        std::lock_guard<std::mutex> lock(state_.mutex);
        ToolState::ExtensionEntry entry;
        entry.name = name;
        entry.extension = std::move(staged);
        entry.attached = true;
        state_.extension_storage.push_back(std::move(entry));
    }
    return {ToolResultStatus::kSuccess, "extension attached"};
}

ExtensionResult ExtensionService::UnregisterExtension(
    const std::string& name) {
    if (g_in_callback) {
        return {ToolResultStatus::kRejected,
                "re-entrant Tool call rejected (TOL-106)"};
    }
    std::unique_ptr<IToolExtension> removed;
    {
        std::lock_guard<std::mutex> lock(state_.mutex);
        if (IsPostRetired(state_.lifecycle_state)) {
            return {ToolResultStatus::kUnavailable,
                    "extension mutation unavailable after kRetired (TOL-088)"};
        }
        auto it = std::find_if(
            state_.extension_storage.begin(), state_.extension_storage.end(),
            [&name](const ToolState::ExtensionEntry& entry) {
                return entry.name == name;
            });
        if (it == state_.extension_storage.end()) {
            return {ToolResultStatus::kNotFound,
                    "unknown extension name (TOL-092)"};
        }
        removed = std::move(it->extension);
        it->attached = false;
        state_.extension_storage.erase(it);
    }
    // Detach outside the domain (TOL-103, TOL-106); Detach
    // failures are normalized: the unregistration is committed
    // and the extension is destroyed before returning.
    if (removed) {
        try {
            CallbackGuard guard;
            removed->Detach(state_.extension_context);
        } catch (...) {
        }
    }
    return {ToolResultStatus::kSuccess, "extension detached"};
}

bool ExtensionService::IsAttached(const std::string& name) const noexcept {
    if (g_in_callback) {
        return false;
    }
    std::lock_guard<std::mutex> lock(state_.mutex);
    if (IsPostRetired(state_.lifecycle_state)) {
        return false;
    }
    const ToolState::ExtensionEntry* entry = state_.FindExtension(name);
    return entry != nullptr && entry->attached;
}

// ------------------------------------------------------------
// ExtensionContext
// ------------------------------------------------------------
const ToolId& ExtensionContext::Id() const noexcept { return state_.id; }

ToolLifecycleState ExtensionContext::LifecycleState() const noexcept {
    std::lock_guard<std::mutex> lock(state_.mutex);
    return state_.lifecycle_state;
}

ToolOperationalState ExtensionContext::OperationalState() const noexcept {
    std::lock_guard<std::mutex> lock(state_.mutex);
    return state_.operational_state;
}

IToolCapabilityService& ExtensionContext::Capabilities() noexcept {
    return state_.capabilities;
}

IToolProviderService& ExtensionContext::Providers() noexcept {
    return state_.providers;
}

// ------------------------------------------------------------
// Tool root
// ------------------------------------------------------------
Tool::Tool(ToolId id, ToolConfiguration configuration)
    : impl_(std::make_unique<Impl>(std::move(id),
                                   std::move(configuration))) {}

Tool::~Tool() = default;

const ToolId& Tool::Id() const noexcept { return impl_->id; }

ToolLifecycleState Tool::LifecycleState() const noexcept {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return impl_->lifecycle_state;
}

ToolOperationalState Tool::OperationalState() const noexcept {
    std::lock_guard<std::mutex> lock(impl_->mutex);
    return impl_->operational_state;
}

ToolLifecycleResult Tool::Register() { return impl_->registration.Register(); }

ToolLifecycleResult Tool::Activate() {
    if (g_in_callback) {
        std::lock_guard<std::mutex> lock(impl_->mutex);
        return MakeLifecycleResult(ToolLifecycleResultStatus::kRejected,
                                   impl_->lifecycle_state,
                                   "re-entrant Tool call rejected (TOL-106)");
    }
    std::lock_guard<std::mutex> lock(impl_->mutex);
    if (impl_->lifecycle_state != ToolLifecycleState::kRegistered) {
        return MakeLifecycleResult(ToolLifecycleResultStatus::kInvalidState,
                                   impl_->lifecycle_state,
                                   "Activate requires kRegistered (TOL-022)");
    }
    impl_->lifecycle_state = ToolLifecycleState::kAvailable;
    impl_->ReevaluateRestricted();
    return MakeLifecycleResult(ToolLifecycleResultStatus::kSuccess,
                               impl_->lifecycle_state, "");
}

ToolLifecycleResult Tool::Suspend() {
    if (g_in_callback) {
        std::lock_guard<std::mutex> lock(impl_->mutex);
        return MakeLifecycleResult(ToolLifecycleResultStatus::kRejected,
                                   impl_->lifecycle_state,
                                   "re-entrant Tool call rejected (TOL-106)");
    }
    std::lock_guard<std::mutex> lock(impl_->mutex);
    if (impl_->lifecycle_state != ToolLifecycleState::kAvailable) {
        return MakeLifecycleResult(ToolLifecycleResultStatus::kInvalidState,
                                   impl_->lifecycle_state,
                                   "Suspend requires kAvailable (TOL-023)");
    }
    impl_->lifecycle_state = ToolLifecycleState::kSuspended;
    impl_->operational_state = ToolOperationalState::kSuspended;
    return MakeLifecycleResult(ToolLifecycleResultStatus::kSuccess,
                               impl_->lifecycle_state, "");
}

ToolLifecycleResult Tool::Resume() {
    if (g_in_callback) {
        std::lock_guard<std::mutex> lock(impl_->mutex);
        return MakeLifecycleResult(ToolLifecycleResultStatus::kRejected,
                                   impl_->lifecycle_state,
                                   "re-entrant Tool call rejected (TOL-106)");
    }
    std::lock_guard<std::mutex> lock(impl_->mutex);
    if (impl_->lifecycle_state != ToolLifecycleState::kSuspended) {
        return MakeLifecycleResult(ToolLifecycleResultStatus::kInvalidState,
                                   impl_->lifecycle_state,
                                   "Resume requires kSuspended (TOL-024)");
    }
    impl_->lifecycle_state = ToolLifecycleState::kAvailable;
    impl_->ReevaluateRestricted();
    return MakeLifecycleResult(ToolLifecycleResultStatus::kSuccess,
                               impl_->lifecycle_state, "");
}

ToolLifecycleResult Tool::Retire() {
    if (g_in_callback) {
        std::lock_guard<std::mutex> lock(impl_->mutex);
        return MakeLifecycleResult(ToolLifecycleResultStatus::kRejected,
                                   impl_->lifecycle_state,
                                   "re-entrant Tool call rejected (TOL-106)");
    }
    std::lock_guard<std::mutex> lock(impl_->mutex);
    if (impl_->lifecycle_state != ToolLifecycleState::kAvailable) {
        return MakeLifecycleResult(ToolLifecycleResultStatus::kInvalidState,
                                   impl_->lifecycle_state,
                                   "Retire requires kAvailable (TOL-025)");
    }
    impl_->lifecycle_state = ToolLifecycleState::kRetiring;
    impl_->operational_state = ToolOperationalState::kRetiring;
    return MakeLifecycleResult(ToolLifecycleResultStatus::kSuccess,
                               impl_->lifecycle_state, "");
}

ToolLifecycleResult Tool::FinalizeRetirement() {
    if (g_in_callback) {
        std::lock_guard<std::mutex> lock(impl_->mutex);
        return MakeLifecycleResult(ToolLifecycleResultStatus::kRejected,
                                   impl_->lifecycle_state,
                                   "re-entrant Tool call rejected (TOL-106)");
    }
    std::lock_guard<std::mutex> lock(impl_->mutex);
    if (impl_->lifecycle_state != ToolLifecycleState::kRetiring) {
        return MakeLifecycleResult(ToolLifecycleResultStatus::kInvalidState,
                                   impl_->lifecycle_state,
                                   "FinalizeRetirement requires kRetiring (TOL-026)");
    }
    impl_->lifecycle_state = ToolLifecycleState::kRetired;
    impl_->operational_state = ToolOperationalState::kRetired;
    return MakeLifecycleResult(ToolLifecycleResultStatus::kSuccess,
                               impl_->lifecycle_state, "");
}

IToolDiscoveryService& Tool::Discovery() noexcept { return impl_->discovery; }
IToolRegistrationService& Tool::Registration() noexcept { return impl_->registration; }
IToolCapabilityService& Tool::Capabilities() noexcept { return impl_->capabilities; }
IToolAvailabilityService& Tool::Availability() noexcept { return impl_->availability; }
IToolPermissionService& Tool::Permissions() noexcept { return impl_->permissions; }
IToolProviderService& Tool::Providers() noexcept { return impl_->providers; }
IToolInvocationPreparationService& Tool::InvocationPreparation() noexcept {
    return impl_->invocation_preparation;
}
IToolExtensionService& Tool::Extensions() noexcept { return impl_->extensions; }

}  // namespace ak::tool