// ============================================================
// memory_runtime_isolation_test.cpp - P1-IS003 Runtime boundary
// ============================================================
// MEM-011 / MEM-012: Memory is Runtime-independent; Phase 2 has
// no concrete Runtime integration (no adapter, binding,
// submission, observation, or translation). Runtime interaction
// is Agent-mediated only and belongs to Phase 5.
// ============================================================

#include <agent_kernel/memory/memory.hpp>
#include <agent_kernel/memory/memory_agent_contract.hpp>
#include <agent_kernel/memory/memory_boundary_validator.hpp>
#include <agent_kernel/memory/memory_provider.hpp>
#include <agent_kernel/memory/memory_services.hpp>

#include <gtest/gtest.h>

#include <type_traits>

#include "test_doubles.hpp"

namespace ak::memory {
namespace {

// Negative API surface: no Phase 5 concrete Runtime operations
// may exist anywhere in the Memory boundary.
template <typename T, typename = void>
struct HasSubmitRuntimeRequest : std::false_type {};
template <typename T>
struct HasSubmitRuntimeRequest<
    T, std::void_t<decltype(std::declval<T&>().SubmitRuntimeRequest())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasObserveRuntimeStatus : std::false_type {};
template <typename T>
struct HasObserveRuntimeStatus<
    T, std::void_t<decltype(std::declval<T&>().ObserveRuntimeStatus())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasTranslateRuntimeRequest : std::false_type {};
template <typename T>
struct HasTranslateRuntimeRequest<
    T, std::void_t<decltype(std::declval<T&>().TranslateRuntimeRequest())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasBindRuntimePublicApi : std::false_type {};
template <typename T>
struct HasBindRuntimePublicApi<
    T, std::void_t<decltype(std::declval<T&>().BindRuntimePublicApi())>>
    : std::true_type {};

TEST(MemoryRuntimeIsolation, Phase2HasNoConcreteRuntimeDependency) {
    static_assert(MemoryBoundaryValidator::Phase2HasNoConcreteRuntimeDependency(),
                  "Phase 2 Memory must be free of concrete Runtime dependency");
}

TEST(MemoryRuntimeIsolation, NoPhase5SurfaceOnMemoryBoundary) {
    static_assert(!HasSubmitRuntimeRequest<Memory>::value,
                  "Memory must not submit Runtime requests in Phase 2");
    static_assert(!HasObserveRuntimeStatus<Memory>::value,
                  "Memory must not observe Runtime status in Phase 2");
    static_assert(!HasTranslateRuntimeRequest<Memory>::value,
                  "Memory must not translate Runtime requests in Phase 2");
    static_assert(!HasBindRuntimePublicApi<Memory>::value,
                  "Memory must not bind the Runtime Public API in Phase 2");
}

TEST(MemoryRuntimeIsolation, NoPhase5SurfaceOnServicesProviderOrContract) {
    static_assert(!HasSubmitRuntimeRequest<MemoryService>::value);
    static_assert(!HasObserveRuntimeStatus<MemoryService>::value);
    static_assert(!HasTranslateRuntimeRequest<MemoryService>::value);

    static_assert(!HasSubmitRuntimeRequest<IMemoryProvider>::value);
    static_assert(!HasObserveRuntimeStatus<IMemoryProvider>::value);

    static_assert(!HasSubmitRuntimeRequest<MemoryAgentContract>::value);
    static_assert(!HasObserveRuntimeStatus<MemoryAgentContract>::value);
    static_assert(!HasTranslateRuntimeRequest<MemoryAgentContract>::value);
}

TEST(MemoryRuntimeIsolation, TuIncludesNoRuntimeHeader) {
    // This TU includes only Memory and Foundation headers; the
    // MemoryBoundaryCheck CTest scans every Memory header and
    // source for Runtime/subsystem includes and validates the
    // agent_kernel_memory link set.
    Memory memory(MakeMemoryIdentity(1));
    EXPECT_TRUE(memory.AgentContract().ContractName() == "Memory");
}

}  // namespace
}  // namespace ak::memory