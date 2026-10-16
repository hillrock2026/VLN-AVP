// ============================================================
// Agent Kernel - AgentModelBinding implementation
// (Agent-owned boundary)
// ============================================================
// P1-IS008 Rev1.0 Chapter 15. The binding is a NON-OWNING
// view over the Model root. Every operation is forwarded to
// the Model root and returns the Model root's own result;
// the binding never interprets ModelResult (interpretation is
// Agent-owned, Chapter 8).
// ============================================================

#include <agent_kernel/agent_model/agent_model_binding.hpp>

namespace ak::agent {

AgentModelBinding::AgentModelBinding(ak::model::Model& model)
    : model_(&model) {}

ak::model::ModelId AgentModelBinding::Id() const noexcept {
    return model_->Id();
}

ak::model::ModelLifecycleState AgentModelBinding::State() const noexcept {
    return model_->State();
}

ak::TransitionResult AgentModelBinding::Initialize() {
    return model_->Initialize();
}

ak::TransitionResult AgentModelBinding::Shutdown() {
    return model_->Shutdown();
}

ak::model::ModelResult AgentModelBinding::Infer(
    const ak::model::ModelInput& input) {
    return model_->Infer(input);
}

}  // namespace ak::agent
