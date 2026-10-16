// ============================================================
// Agent Kernel - SubsystemContract (Agent boundary)
// ============================================================
// Minimal architectural contract surface that a peer
// subsystem exposes to the Agent.
//
// P1-IS002 scope (Chapter 9 - Agent Coordination Architecture,
// Chapter 19 - Dependency Model):
// - The Agent is the sole cross-subsystem coordinator and
//   coordinates Memory, Context, Planner, and Tool through
//   their architectural contracts, not through their internal
//   extensions.
// - Agent -> Memory/Context/Planner/Tool contracts are
//   permitted Phase 1 dependencies.
//
// NON-responsibilities:
// - These contracts do NOT implement subsystem behavior;
//   Memory/Context/Planner/Tool retain ownership of their
//   own responsibilities.
// - No subsystem acquires hidden coordination authority
//   through these contracts.
// ============================================================

#pragma once

#include <cstdint>
#include <string_view>

namespace ak::agent {

// Identifies the peer architectural subsystem.
enum class SubsystemId : std::uint8_t {
    kMemory = 0,
    kContext,
    kPlanner,
    kTool
};

// Result of a Phase 1 coordination acknowledgment.
struct CoordinationAcknowledgement {
    bool accepted = false;
    const char* message = "";
};

// Abstract architectural contract a peer subsystem exposes to
// the Agent. The Agent coordinates the subsystem through this
// contract; the subsystem remains the architectural owner of
// its own behavior.
class ISubsystemContract {
public:
    virtual ~ISubsystemContract() noexcept = default;

    // Name of the architectural contract (e.g., "Memory").
    [[nodiscard]] virtual std::string_view ContractName() const noexcept = 0;

    // Acknowledges Agent coordination. Phase 1 boundary only:
    // no subsystem behavior is implemented by the Agent.
    [[nodiscard]] virtual CoordinationAcknowledgement AcknowledgeCoordination() = 0;
};

}  // namespace ak::agent
