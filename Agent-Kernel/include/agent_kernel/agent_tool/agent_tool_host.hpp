// ============================================================
// Agent Kernel - AgentToolHost (Agent-owned composition root)
// ============================================================
// P1-IS006 Rev2 Chapter 25 - the single production composition
// root for Phase 4 Tool integration (TOL-057).
//
// Construction order is normative (TOL-059):
//   AgentToolHost -> Tool -> AgentToolBinding
// Member order: tool_, binding_ (declaration order = init
// order); destruction occurs in reverse order: binding_, tool_.
//
// AgentToolHost owns Tool (TOL-058); AgentToolBinding is a
// non-owning view over Tool. The host SHALL NOT expose a
// public Tool() accessor (TOL-084): the Agent coordinates the
// Tool exclusively through AgentToolHost::Binding() (TOL-101).
//
// NON-responsibilities:
// - The host performs no Runtime action (TOL-060); the Phase 4
//   production path terminates at Tool.
// ============================================================

#pragma once

#include <agent_kernel/agent_tool/agent_tool_binding.hpp>
#include <agent_kernel/tool/tool.hpp>

namespace ak::agent {

// The single production composition root (TOL-057).
class AgentToolHost final {
public:
    AgentToolHost(ak::tool::ToolId tool_id,
                  ak::tool::ToolConfiguration configuration);

    AgentToolHost(const AgentToolHost&) = delete;
    AgentToolHost& operator=(const AgentToolHost&) = delete;

    // -- Agent-owned production surface --
    [[nodiscard]] const AgentToolBinding& Binding() const noexcept;
    [[nodiscard]] AgentToolBinding& Binding() noexcept;

private:
    // member order is normative (declaration order = init order)
    ak::tool::Tool tool_;
    AgentToolBinding binding_;
};

}  // namespace ak::agent