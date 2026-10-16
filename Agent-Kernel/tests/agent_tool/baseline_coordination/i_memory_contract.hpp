// ============================================================
// Agent Kernel - IMemoryContract (Agent boundary)
// ============================================================
// Memory architectural contract surface.
//
// P1-IS002 scope:
// - Agent coordinates Memory through its architectural
//   contract (AK0042). Memory owns knowledge retention; the
//   Agent does not implement or absorb Memory behavior.
// ============================================================

#pragma once

#include <agent_kernel/agent/coordination/subsystem_contract.hpp>

namespace ak::agent {

class IMemoryContract : public ISubsystemContract {
public:
    ~IMemoryContract() noexcept override = default;
};

}  // namespace ak::agent
