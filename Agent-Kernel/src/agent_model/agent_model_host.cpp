// ============================================================
// Agent Kernel - AgentModelHost implementation (Agent-owned
// composition root)
// ============================================================
// P1-IS008 Rev1.0 Chapters 7, 15. Member order is normative:
// model_, binding_ (declaration order = init order);
// destruction occurs in reverse order: binding_, model_
// (Chapter 19.5 pattern of P1-IS007 Rev1.1).
//
// The host owns the injected Model root; constructing the host
// is ordinary object construction and is NOT Agent or Runtime
// lifecycle authority (Chapter 10).
// ============================================================

#include <agent_kernel/agent_model/agent_model_host.hpp>

#include <stdexcept>
#include <utility>

namespace ak::agent {
namespace {

std::unique_ptr<ak::model::Model> RequireNonNullModel(
    std::unique_ptr<ak::model::Model> model) {
    if (!model) {
        throw std::invalid_argument(
            "AgentModelHost requires a non-null Model");
    }
    return model;
}

}  // namespace

AgentModelHost::AgentModelHost(std::unique_ptr<ak::model::Model> model)
    : model_(RequireNonNullModel(std::move(model))), binding_(*model_) {}

AgentModelBinding& AgentModelHost::Binding() noexcept {
    return binding_;
}

const AgentModelBinding& AgentModelHost::Binding() const noexcept {
    return binding_;
}

}  // namespace ak::agent
