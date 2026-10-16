// ============================================================
// Agent Kernel - PlannerExtensions (Planner boundary)
// ============================================================
// Planner-owned extension boundary (P1-IS005 Rev5.1 Chapter
// 7.4; AK0044 Revision A Section 15), following the P1-IS004
// extension-boundary pattern.
//
// Rules:
// - Only kPlanner domain extensions SHALL attach; foreign
//   domains are rejected.
// - Extensions SHALL NOT change Planner ownership, become
//   lifecycle authorities, coordinate or bypass Agent, access
//   Runtime internals, execute Runtime objects, or change
//   Memory/Context/Runtime ownership.
// - Extensions SHALL NOT become the owner of the Planner
//   exchange model, contracts, or lifecycle.
//
// NON-responsibilities:
// - This is not a plugin framework and not a second extension
//   framework; it is the P1-IS001/IS004-compatible boundary.
// ============================================================

#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace ak::planner {

enum class PlannerExtensionDomain : std::uint8_t {
    kPlanner = 0,
    kAgent,
    kMemory,
    kContext,
    kTool,
    kUnknown
};

class IPlannerExtension {
public:
    virtual ~IPlannerExtension() noexcept = default;

    [[nodiscard]] virtual std::string_view Name() const noexcept = 0;
    [[nodiscard]] virtual PlannerExtensionDomain Domain() const noexcept = 0;
    [[nodiscard]] virtual std::uint32_t MajorVersion() const noexcept = 0;
    [[nodiscard]] virtual bool SelfCheck() const noexcept = 0;
};

struct PlannerAttachResult {
    bool accepted = false;
    const char* message = "";
};

class PlannerExtensionBoundary {
public:
    PlannerExtensionBoundary() = default;

    PlannerAttachResult Attach(std::shared_ptr<IPlannerExtension> extension);
    bool Detach(std::string_view name);
    [[nodiscard]] std::size_t Count() const noexcept;
    [[nodiscard]] bool Contains(std::string_view name) const noexcept;
    [[nodiscard]] std::vector<std::string> Enumerate() const;
    [[nodiscard]] bool ValidateIntegrity() const noexcept;
    [[nodiscard]] bool ContainsForeignExtension() const noexcept;
    [[nodiscard]] static constexpr std::uint32_t SupportedMajorVersion() noexcept {
        return 1;
    }

private:
    struct Entry {
        std::shared_ptr<IPlannerExtension> extension;
    };
    std::vector<Entry> entries_;
};

}  // namespace ak::planner
