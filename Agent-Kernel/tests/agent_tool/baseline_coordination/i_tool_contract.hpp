// ============================================================
// Agent Kernel - IToolContract (Agent boundary)
// ============================================================
// Tool architectural contract surface.
//
// P1-IS002 scope:
// - Agent coordinates Tool through its architectural contract
//   (AK0045). Tool owns capability representation; the Agent
//   does not implement or absorb Tool capability ownership.
// ============================================================

#pragma once

#include <agent_kernel/agent/coordination/subsystem_contract.hpp>

namespace ak::agent {

class IToolContract : public ISubsystemContract {
public:
    ~IToolContract() noexcept override = default;
};

}  // namespace ak::agent
