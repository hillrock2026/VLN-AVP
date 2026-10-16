// ============================================================
// Agent Kernel - Model Identity (Model boundary)
// ============================================================
// P1-IS008 Rev1.0 Chapter 7 - Model implementation boundary.
//
// ModelId is the immutable Model identity value type. It follows
// the canonical identity conventions established by ToolId
// (P1-IS006 Rev2 Chapter 8, TOL-013) and PromptId (P1-IS007
// Rev1.1 Chapter 8): construction rejects empty or
// whitespace-only values with std::invalid_argument.
//
// Concrete C++ signature decision (P1-IS008 Rev1.0 F-001,
// Chapter 27): P1-IS008 defines the Model semantic contract
// without prescribing class signatures. ModelId is chosen for
// consistency with the existing Agent Kernel root-identity
// convention (AgentIdentity, PlannerIdentity, ToolId, PromptId)
// and to support implementation traceability (IS-AC-020).
//
// NON-responsibilities:
// - ModelId is not a Runtime identity and references no Runtime
//   type; it confers no execution or lifecycle authority.
// ============================================================

#pragma once

#include <string>
#include <utility>

namespace ak::model {

// Canonical Model architectural identity.
class ModelId {
public:
    ModelId() = delete;
    explicit ModelId(std::string value);

    [[nodiscard]] const std::string& Value() const noexcept { return value_; }

    friend bool operator==(const ModelId&, const ModelId&) = default;

private:
    std::string value_;
};

}  // namespace ak::model
