// ============================================================
// Agent Kernel - IContextContract (Agent boundary)
// ============================================================
// Context architectural contract surface.
//
// P1-IS002 scope:
// - Agent coordinates Context through its architectural
//   contract (AK0043). Context owns execution context and
//   intelligent working state; the Agent does not implement or
//   absorb Context behavior.
// ============================================================

#pragma once

#include <agent_kernel/agent/coordination/subsystem_contract.hpp>

namespace ak::agent {

class IContextContract : public ISubsystemContract {
public:
    ~IContextContract() noexcept override = default;
};

}  // namespace ak::agent
