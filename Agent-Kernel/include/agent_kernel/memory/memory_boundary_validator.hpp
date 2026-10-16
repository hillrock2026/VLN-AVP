// ============================================================
// Agent Kernel - MemoryBoundaryValidator (Memory boundary)
// ============================================================
// Memory-owned ownership and dependency validation.
//
// P1-IS003 scope (Chapter 18 - Test Strategy, Chapter 15):
// - Validates the Memory representation: identity, normative
//   lifecycle and operational state, provider registration,
//   extension-boundary isolation, and lifecycle/state
//   separation.
// - The static include/link boundary is enforced by the CMake
//   Memory boundary check (tests/memory/
//   check_memory_boundaries.cmake); this validator performs
//   executable representation-level validation.
//
// NON-responsibilities:
// - The validator owns no Memory state and cannot initiate
//   lifecycle or operational transitions.
// ============================================================

#pragma once

#include <type_traits>

#include <agent_kernel/foundation/kernel_diagnostics.hpp>
#include <agent_kernel/memory/memory.hpp>

namespace ak::memory {

class MemoryBoundaryValidator {
public:
    MemoryBoundaryValidator() = default;

    // Validates the Memory representation and appends
    // diagnostics to the caller-provided owner-scoped sink.
    void Validate(const Memory& memory, ak::DiagnosticSink& sink) const;

    // Phase 2 static property: no concrete Runtime dependency
    // and no Runtime integration.
    [[nodiscard]] static constexpr bool Phase2HasNoConcreteRuntimeDependency() noexcept {
        return true;
    }

    // Compile-time separation proof: lifecycle and operational
    // state are distinct state models.
    static_assert(!std::is_same_v<MemoryLifecycleState, MemoryOperationalState>,
                  "lifecycle and operational state must remain distinct models");
};

}  // namespace ak::memory