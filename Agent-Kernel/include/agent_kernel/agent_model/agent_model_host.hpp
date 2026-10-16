// ============================================================
// Agent Kernel - AgentModelHost (Agent-owned composition root)
// ============================================================
// P1-IS008 Rev1.0 Chapters 7, 15 - the production composition
// root for Model integration.
//
// Construction order is normative (following the P1-IS005
// Chapter 16 / P1-IS006 Rev2 Chapter 25 / P1-IS007 Rev1.1
// Chapter 19.5 pattern):
//   AgentModelHost -> Model -> AgentModelBinding
// Member order: model_, binding_ (declaration order = init
// order); destruction occurs in reverse order: binding_, model_.
//
// AgentModelHost owns the Model root (the Model instance is
// injected at construction). Rev1 has no production concrete
// Model; the deterministic Model required for acceptance
// (Chapter 13) is a test double injected at composition, and
// the host never creates provider SDK types (Chapters 11, 16).
//
// The host SHALL NOT expose a public Model() accessor: the
// Agent coordinates Model exclusively through
// AgentModelHost::Binding().
//
// NON-responsibilities:
// - The host performs no Runtime action and is not a second
//   composition root (Chapters 15, 16).
// ============================================================

#pragma once

#include <memory>

#include <agent_kernel/agent_model/agent_model_binding.hpp>
#include <agent_kernel/model/model.hpp>
#include <agent_kernel/foundation/kernel_lifecycle.hpp>

namespace ak::agent {

// The production composition root for Model integration.
class AgentModelHost final {
public:
    // Takes ownership of the Model root. A null Model is
    // rejected with std::invalid_argument (deterministic
    // construction failure).
    explicit AgentModelHost(std::unique_ptr<ak::model::Model> model);

    AgentModelHost(const AgentModelHost&) = delete;
    AgentModelHost& operator=(const AgentModelHost&) = delete;
    AgentModelHost(AgentModelHost&&) = delete;
    AgentModelHost& operator=(AgentModelHost&&) = delete;

    ~AgentModelHost() = default;

    // -- Agent-owned production surface --
    [[nodiscard]] const AgentModelBinding& Binding() const noexcept;
    [[nodiscard]] AgentModelBinding& Binding() noexcept;

private:
    // member order is normative (declaration order = init order)
    std::unique_ptr<ak::model::Model> model_;
    AgentModelBinding binding_;
};

}  // namespace ak::agent
