// ============================================================
// Agent Kernel - AgentToolHost implementation (Agent-owned
// composition root)
// ============================================================
// P1-IS006 Rev2 Chapter 25. Member order is normative:
// tool_, binding_ (declaration order = init order); destruction
// occurs in reverse order: binding_, tool_ (TOL-059).
//
// NON-responsibilities:
// - No Runtime action (TOL-060); the host exposes no public
//   Tool() accessor (TOL-084).
// ============================================================

#include <agent_kernel/agent_tool/agent_tool_host.hpp>

#include <utility>

namespace ak::agent {

AgentToolHost::AgentToolHost(ak::tool::ToolId tool_id,
                             ak::tool::ToolConfiguration configuration)
    : tool_(std::move(tool_id), std::move(configuration)),
      binding_(tool_) {}

AgentToolBinding& AgentToolHost::Binding() noexcept { return binding_; }

const AgentToolBinding& AgentToolHost::Binding() const noexcept {
    return binding_;
}

}  // namespace ak::agent