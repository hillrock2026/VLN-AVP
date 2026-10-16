// ============================================================
// Agent Kernel - IPlannerContract (Agent boundary)
// ============================================================
// Planner architectural contract surface.
//
// P1-IS002 scope:
// - Agent coordinates Planner through its architectural
//   contract (AK0044). Planner owns planning; the Agent does
//   not implement or absorb planning.
// ============================================================

#pragma once

#include <agent_kernel/agent/coordination/subsystem_contract.hpp>

namespace ak::agent {

class IPlannerContract : public ISubsystemContract {
public:
    ~IPlannerContract() noexcept override = default;
};

}  // namespace ak::agent
