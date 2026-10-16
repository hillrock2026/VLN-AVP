// ============================================================
// deterministic_test_executor.hpp - First Working Agent Sprint
// ============================================================
// TEST ONLY (TASK 6 Rev2 §20; TASK 5 OBS-03). Test-scoped Tool
// execution stand-in. It is a TEST LOCAL executor and SHALL
// NEVER be compiled into a production target; Tool execution
// remains a Runtime / future boundary responsibility (INV-014).
//
// FWA-T7 / TASK-6-Rev2 / STEP-10 / AC-009 / AC-015
// ============================================================

#pragma once

#include <string>

#include <agent_kernel/tool/tool_identity.hpp>

namespace ak::agent {
namespace test {

// Deterministic execution stand-in: returns the deterministic
// observation value that the composition writes into Context.
inline std::string DeterministicTestExecutor(
    const ak::tool::CapabilityId& capability,
    const std::string& payload) {
    return std::string("[tool-result] ") + capability.Value() + ":" + payload;
}

}  // namespace test
}  // namespace ak::agent
