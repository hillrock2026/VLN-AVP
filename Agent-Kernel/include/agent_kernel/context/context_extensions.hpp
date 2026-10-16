// ============================================================
// Agent Kernel - ContextExtensionBoundary (Context boundary)
// ============================================================
// Context-owned extension boundary.
//
// P1-IS004 scope (Chapter 16 - Context Extension Architecture,
// Chapter 27):
// - Context extensions attach only to Context.
// - Context owns extension lifecycle, state, configuration,
//     integrity, compatibility, and governance.
// - Non-Context extensions (Agent/Memory/Planner/Tool/Unknown)
//     SHALL be rejected.
// - Future Context capabilities are introduced through
//     composition: extensions MAY add Context Services, Context
//     Object categories, contextual relationships, or other
//     implementation-independent capabilities, but SHALL NOT
//     redefine Context ownership.
//
// NON-responsibilities:
// - This boundary is an implementation boundary/mechanism, not
//   a new Kernel architectural subsystem named "Extension".
// - Extensions cannot become cross-subsystem coordinators,
//   cannot bypass Agent coordination, cannot bypass the Runtime
//   Public API, and cannot acquire Runtime or Agent ownership.
// ============================================================

#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

#include <agent_kernel/foundation/kernel_diagnostics.hpp>
#include <agent_kernel/foundation/kernel_metadata.hpp>
#include <agent_kernel/context/context_result.hpp>

namespace ak::context {

// Architectural domain of an extension. Only the Context domain
// may attach to the Context extension boundary.
enum class ContextExtensionDomain : std::uint8_t {
    kContext = 0,
    kAgent,
    kMemory,
    kPlanner,
    kTool,
    kUnknown
};

struct ContextExtensionVersion {
    std::uint32_t major = 0;
    std::uint32_t minor = 0;
};

struct ContextAttachResult {
    bool accepted = false;
    const char* message = "";
};

// Interface implemented by Context-owned extensions. Extensions
// owned by other subsystems SHALL NOT implement this interface.
class IContextExtension {
public:
    virtual ~IContextExtension() noexcept = default;

    [[nodiscard]] virtual std::string_view Name() const noexcept = 0;
    [[nodiscard]] virtual ContextExtensionDomain Domain() const noexcept = 0;
    [[nodiscard]] virtual ContextExtensionVersion Version() const noexcept = 0;
    [[nodiscard]] virtual bool SelfCheck() const noexcept = 0;
};

// Internal extension lifecycle/state managed by the boundary on
// behalf of Context. Not an architectural state of Context.
enum class ContextExtensionState : std::uint8_t {
    kDetached = 0,
    kAttached,
    kActive,
    kSuspended
};

class ContextExtensionBoundary {
public:
    ContextExtensionBoundary() = default;

    // Attaches a Context-owned extension. Foreign domains are
    // rejected.
    ContextAttachResult Attach(std::shared_ptr<IContextExtension> extension);
    bool Detach(std::string_view name);

    // -- Context-owned extension lifecycle --
    bool Activate(std::string_view name);
    bool Suspend(std::string_view name);

    // -- Context-owned extension configuration --
    bool SetConfiguration(std::string_view name, ak::KernelMetadata configuration);

    // -- Query --
    [[nodiscard]] std::size_t Count() const noexcept { return entries_.size(); }
    [[nodiscard]] bool Contains(std::string_view name) const noexcept;
    [[nodiscard]] std::vector<std::string> Enumerate() const;
    [[nodiscard]] ContextExtensionState GetState(std::string_view name) const noexcept;

    // -- Integrity and compatibility (Context-owned governance) --
    [[nodiscard]] bool ValidateIntegrity() const noexcept;
    [[nodiscard]] bool ValidateCompatibility() const noexcept;
    void ValidateBoundary(ak::DiagnosticSink& sink) const;

    // True when a non-Context extension is attached. A
    // conforming boundary is always false here.
    [[nodiscard]] bool ContainsForeignExtension() const noexcept;

    [[nodiscard]] static constexpr std::uint32_t SupportedMajorVersion() noexcept {
        return 1;
    }

private:
    struct Entry {
        std::shared_ptr<IContextExtension> extension;
        ContextExtensionState state = ContextExtensionState::kAttached;
        ak::KernelMetadata configuration;
    };

    [[nodiscard]] Entry* Find(std::string_view name) noexcept;
    [[nodiscard]] const Entry* Find(std::string_view name) const noexcept;

    std::vector<Entry> entries_;
};

}  // namespace ak::context
