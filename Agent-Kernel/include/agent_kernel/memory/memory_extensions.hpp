// ============================================================
// Agent Kernel - MemoryExtensionBoundary (Memory boundary)
// ============================================================
// Memory-owned extension boundary.
//
// P1-IS003 scope (Chapter 14 - Memory Extension Boundary,
// Chapter 16.1):
// - Memory extensions attach only to Memory.
// - Memory owns extension lifecycle, state, configuration,
//     integrity, compatibility, and governance.
// - Non-Memory extensions (Agent/Context/Planner/Tool/Unknown)
//     SHALL be rejected.
//
// NON-responsibilities:
// - This boundary is an implementation boundary/mechanism, not
//   a new Kernel architectural subsystem named "Extension".
// - Extensions cannot become cross-subsystem coordinators and
//   cannot bypass the Agent or Runtime boundary.
// ============================================================

#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

#include <agent_kernel/foundation/kernel_diagnostics.hpp>
#include <agent_kernel/foundation/kernel_metadata.hpp>
#include <agent_kernel/memory/memory_result.hpp>

namespace ak::memory {

// Architectural domain of an extension. Only the Memory domain
// may attach to the Memory extension boundary.
enum class MemoryExtensionDomain : std::uint8_t {
    kMemory = 0,
    kAgent,
    kContext,
    kPlanner,
    kTool,
    kUnknown
};

struct MemoryExtensionVersion {
    std::uint32_t major = 0;
    std::uint32_t minor = 0;
};

struct MemoryAttachResult {
    bool accepted = false;
    const char* message = "";
};

// Interface implemented by Memory-owned extensions. Extensions
// owned by other subsystems SHALL NOT implement this interface.
class IMemoryExtension {
public:
    virtual ~IMemoryExtension() noexcept = default;

    [[nodiscard]] virtual std::string_view Name() const noexcept = 0;
    [[nodiscard]] virtual MemoryExtensionDomain Domain() const noexcept = 0;
    [[nodiscard]] virtual MemoryExtensionVersion Version() const noexcept = 0;
    [[nodiscard]] virtual bool SelfCheck() const noexcept = 0;
};

// Internal extension lifecycle/state managed by the boundary on
// behalf of Memory. Not an architectural state of Memory.
enum class MemoryExtensionState : std::uint8_t {
    kDetached = 0,
    kAttached,
    kActive,
    kSuspended
};

class MemoryExtensionBoundary {
public:
    MemoryExtensionBoundary() = default;

    // Attaches a Memory-owned extension. Foreign domains are
    // rejected.
    MemoryAttachResult Attach(std::shared_ptr<IMemoryExtension> extension);
    bool Detach(std::string_view name);

    // -- Memory-owned extension lifecycle --
    bool Activate(std::string_view name);
    bool Suspend(std::string_view name);

    // -- Memory-owned extension configuration --
    bool SetConfiguration(std::string_view name, ak::KernelMetadata configuration);

    // -- Query --
    [[nodiscard]] std::size_t Count() const noexcept { return entries_.size(); }
    [[nodiscard]] bool Contains(std::string_view name) const noexcept;
    [[nodiscard]] std::vector<std::string> Enumerate() const;
    [[nodiscard]] MemoryExtensionState GetState(std::string_view name) const noexcept;

    // -- Integrity and compatibility (Memory-owned governance) --
    [[nodiscard]] bool ValidateIntegrity() const noexcept;
    [[nodiscard]] bool ValidateCompatibility() const noexcept;
    void ValidateBoundary(ak::DiagnosticSink& sink) const;

    // True when a non-Memory extension is attached. A conforming
    // boundary is always false here.
    [[nodiscard]] bool ContainsForeignExtension() const noexcept;

    [[nodiscard]] static constexpr std::uint32_t SupportedMajorVersion() noexcept {
        return 1;
    }

private:
    struct Entry {
        std::shared_ptr<IMemoryExtension> extension;
        MemoryExtensionState state = MemoryExtensionState::kAttached;
        ak::KernelMetadata configuration;
    };

    [[nodiscard]] Entry* Find(std::string_view name) noexcept;
    [[nodiscard]] const Entry* Find(std::string_view name) const noexcept;

    std::vector<Entry> entries_;
};

}  // namespace ak::memory