// ============================================================
// Agent Kernel - Model (Model boundary)
// ============================================================
// P1-IS008 Rev1.0 Chapters 7, 11 - the Model contract.
//
// Model provides inference. Agent owns intelligent execution
// (Chapter 4, AK0046). The Agent invokes Model through the
// Model boundary; Model consumes model-facing input, performs
// inference, and produces ModelResult (Chapter 7).
//
// Minimum public semantic contract:
//   Model receives Model input.
//   Model performs inference.
//   Model returns ModelResult.
//
// Model does NOT coordinate Agent, control Agent lifecycle,
// execute Tool, own Tool lifecycle, access Runtime internals,
// own Runtime lifecycle, own Memory, own Context, replace
// Planner, or assemble its own input (Chapters 4, 7, 16).
//
// Model lifecycle is distinct from Agent and Runtime lifecycle
// (Chapter 10). One inference operation is:
//   Ready -> Inference -> Result.
//
// Concrete signature decision (F-001, Chapter 27): the Model
// boundary is expressed as a minimal abstract contract so that
// Agent depends on the Model abstraction and never on a
// concrete provider SDK (Chapter 11). Rev1 introduces no
// registries, managers, routers, schedulers, caches, sessions,
// or streaming abstractions (Chapter 7).
//
// NON-responsibilities:
// - Model performs no Runtime action and references no Runtime
//   type.
// ============================================================

#pragma once

#include <agent_kernel/model/model_identity.hpp>
#include <agent_kernel/model/model_input.hpp>
#include <agent_kernel/model/model_result.hpp>
#include <agent_kernel/model/model_state.hpp>
#include <agent_kernel/foundation/kernel_lifecycle.hpp>

namespace ak::model {

// The minimal Model inference contract (Chapter 7).
class Model {
public:
    Model() = default;
    virtual ~Model() = default;

    // Default copy/move are retained so concrete Model value
    // implementations (for example the deterministic test double)
    // keep ordinary value semantics; abstractness prevents base
    // slicing.
    Model(const Model&) = default;
    Model& operator=(const Model&) = default;
    Model(Model&&) = default;
    Model& operator=(Model&&) = default;

    // -- identity / state --
    [[nodiscard]] virtual ModelId Id() const noexcept = 0;
    [[nodiscard]] virtual ModelLifecycleState State() const noexcept = 0;

    // -- lifecycle (Model-owned; distinct from Agent/Runtime) --
    // Initialization establishes Model configuration/provider
    // binding (Chapter 10). Uninitialized -> Ready, or ->
    // Unavailable when the provider is unavailable.
    [[nodiscard]] virtual ak::TransitionResult Initialize() = 0;

    // Shutdown releases only Model-owned resources (Chapter 10).
    [[nodiscard]] virtual ak::TransitionResult Shutdown() = 0;

    // -- inference --
    // Accepts the immutable model-facing input and produces the
    // Model-owned inference result (Chapters 7, 8).
    [[nodiscard]] virtual ModelResult Infer(const ModelInput& input) = 0;
};

}  // namespace ak::model
