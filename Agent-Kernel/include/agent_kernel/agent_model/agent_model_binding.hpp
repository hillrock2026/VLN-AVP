// ============================================================
// Agent Kernel - AgentModelBinding (Agent-owned boundary)
// ============================================================
// P1-IS008 Rev1.0 Chapters 7, 15 - the sole Agent-facing Model
// coordination boundary.
//
// AgentModelBinding is a NON-OWNING view over the Model root:
// it does not own Model and maintains no independent Model
// lifecycle state; every operation is forwarded to the Model
// root and returns the Model root's own result (Chapter 15).
// It follows the Agent-facing composition, ownership, and
// non-owning reference pattern established by AgentPlannerBinding
// (P1-IS005), AgentToolBinding (P1-IS006 Rev2), and
// AgentPromptBinding (P1-IS007 Rev1.1).
//
// Direction: Agent -> Model for invocation; Model -> ModelResult
// -> Agent for result return (Chapter 15). The binding never
// interprets the result; interpretation is Agent-owned.
//
// NON-responsibilities:
// - No Runtime operation, no Tool operation, no second Model
//   API, and no lifecycle authority beyond forwarding Model
//   lifecycle (Chapters 9, 15, 16).
// - The binding does not expose ModelAction and does not move
//   ModelAction into the Model boundary.
// ============================================================

#pragma once

#include <agent_kernel/model/model.hpp>
#include <agent_kernel/foundation/kernel_lifecycle.hpp>

namespace ak::agent {

// The sole Agent-facing Model coordination boundary (Chapter 15).
class AgentModelBinding final {
public:
    // `model` must outlive the binding.
    explicit AgentModelBinding(ak::model::Model& model);

    AgentModelBinding(const AgentModelBinding&) = delete;
    AgentModelBinding& operator=(const AgentModelBinding&) = delete;
    AgentModelBinding(AgentModelBinding&&) = delete;
    AgentModelBinding& operator=(AgentModelBinding&&) = delete;

    ~AgentModelBinding() = default;

    // -- identity / state (forwarded to the Model root) --
    [[nodiscard]] ak::model::ModelId Id() const noexcept;
    [[nodiscard]] ak::model::ModelLifecycleState State() const noexcept;

    // -- lifecycle (forwarded; Model-owned) --
    [[nodiscard]] ak::TransitionResult Initialize();
    [[nodiscard]] ak::TransitionResult Shutdown();

    // -- inference (forwarded) --
    // Agent invokes Model through this boundary; the Model-owned
    // ModelResult is returned for Agent interpretation.
    [[nodiscard]] ak::model::ModelResult Infer(
        const ak::model::ModelInput& input);

private:
    ak::model::Model* model_ = nullptr;
};

}  // namespace ak::agent
