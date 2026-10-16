// ============================================================
// Agent Kernel - MemoryAgentContract (Memory boundary)
// ============================================================
// Agent-facing Memory coordination contract.
//
// P1-IS003 scope (Chapter 12 - Interaction Contract, Chapter
// 10):
// - The Agent is the sole architectural coordinator of Memory.
// - This contract is the Agent-facing surface: lifecycle
//   participation requests, operational-state inspection, and
//   Memory Service invocation.
// - The contract is expressed inside the Memory boundary so
//   that Memory never depends on Agent headers (no reverse
//   target dependency and no circular link).
//
// NON-responsibilities:
// - This contract grants Memory no cross-subsystem
//   coordination authority and no Agent access.
// - It references no Runtime type and performs no Runtime
//   action.
// ============================================================

#pragma once

#include <cstdint>
#include <string_view>

#include <agent_kernel/memory/memory_services.hpp>
#include <agent_kernel/memory/memory_state.hpp>

namespace ak::memory {

class Memory;

// Lifecycle participation the Agent may request. Memory owns
// and validates every resulting transition.
enum class MemoryLifecycleParticipation : std::uint8_t {
    kInitialize = 0,
    kActivate,
    kSuspend,
    kResume,
    kTerminate,
    kDispose
};

class MemoryAgentContract {
public:
    explicit MemoryAgentContract(Memory& memory) noexcept : memory_(&memory) {}

    // Architectural contract name (AK0042 "Memory").
    [[nodiscard]] std::string_view ContractName() const noexcept {
        return "Memory";
    }

    // Agent requests lifecycle participation; Memory owns the
    // transition and may reject it.
    [[nodiscard]] MemoryResult RequestLifecycleParticipation(
        MemoryLifecycleParticipation request);

    // Agent inspection (read-only): Memory retains ownership.
    [[nodiscard]] MemoryLifecycleState InspectLifecycleState() const noexcept;
    [[nodiscard]] MemoryOperationalState InspectOperationalState() const noexcept;

    // Memory Service invocation through the Agent-facing
    // contract.
    [[nodiscard]] MemoryService& Services() noexcept;
    [[nodiscard]] const MemoryService& Services() const noexcept;

private:
    Memory* memory_ = nullptr;
};

}  // namespace ak::memory