// ============================================================
// Agent Kernel - ModelAction (Agent boundary)
// ============================================================
// TASK 3 §12 — Minimum Integration Contract. First Working
// Agent Sprint.
//
// ModelAction is the minimum deterministic action representation
// produced by the composition-owned Model boundary. It closes
// CSV-GAP-001 at the implementation level (TASK 6 Rev2 §11).
//
// Ownership: Agent boundary. Value type only: immutable, copyable,
// no virtuals, no lifecycle, no Context/Tool/Runtime access.
//
// kInvalid is the sole failure kind; Reason() carries the stable
// failure evidence (recorded into Agent diagnostics / Context by
// the composition loop, TASK 6 Rev2 §24 case 3).
//
// NON-responsibilities:
// - ModelAction is NOT a Model subsystem, registry, provider,
//   router, cache, or scheduler (Sprint Chapter 12.2).
// - It references no Runtime type.
// ============================================================

#pragma once

#include <cstdint>
#include <optional>
#include <string>

#include <agent_kernel/tool/tool_identity.hpp>

namespace ak::agent {

// The deterministic action kinds a Model boundary may produce
// (TASK 3 §12; TASK 4 §12).
enum class ModelActionKind : std::uint8_t {
    kToolInvoke = 0,  // invoke a Tool capability with arguments
    kComplete,        // the Agent task is complete
    kInvalid          // the model output cannot be interpreted as a supported action
};

// Immutable Agent-owned value representation of one Model
// decision (TASK 3 §12 public API — verbatim, no extension).
class ModelAction final {
public:
    // Requires a non-empty CapabilityId (the identity type itself
    // rejects empty values deterministically, TOL-111).
    static ModelAction InvokeTool(ak::tool::CapabilityId capability,
                                  std::string arguments) {
        ModelAction action;
        action.kind_ = ModelActionKind::kToolInvoke;
        action.capability_ = std::move(capability);
        action.arguments_ = std::move(arguments);
        return action;
    }

    static ModelAction Complete() {
        ModelAction action;
        action.kind_ = ModelActionKind::kComplete;
        return action;
    }

    static ModelAction Invalid(std::string reason) {
        ModelAction action;
        action.kind_ = ModelActionKind::kInvalid;
        action.reason_ = std::move(reason);
        return action;
    }

    [[nodiscard]] ModelActionKind Kind() const noexcept { return kind_; }
    [[nodiscard]] bool IsToolInvoke() const noexcept {
        return kind_ == ModelActionKind::kToolInvoke;
    }
    [[nodiscard]] bool IsComplete() const noexcept {
        return kind_ == ModelActionKind::kComplete;
    }
    [[nodiscard]] bool IsInvalid() const noexcept {
        return kind_ == ModelActionKind::kInvalid;
    }

    // Valid only when Kind() == kToolInvoke (nullptr otherwise).
    [[nodiscard]] const ak::tool::CapabilityId* Capability() const noexcept {
        return capability_ ? &*capability_ : nullptr;
    }

    // Valid only when Kind() == kToolInvoke.
    [[nodiscard]] const std::string& Arguments() const noexcept {
        return arguments_;
    }

    // Valid only when Kind() == kInvalid; stable failure reason.
    [[nodiscard]] const std::string& Reason() const noexcept { return reason_; }

private:
    ModelAction() = default;

    ModelActionKind kind_ = ModelActionKind::kInvalid;
    std::optional<ak::tool::CapabilityId> capability_;
    std::string arguments_;
    std::string reason_;
};

}  // namespace ak::agent
