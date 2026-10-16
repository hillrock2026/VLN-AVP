// ============================================================
// runtime_isolation_test.cpp - P1-IS002 Runtime phase boundary
// ============================================================
// AG-010..AG-014: Phase 1 establishes only the Agent-owned
// Runtime interaction port/contract plus static isolation
// validation. No concrete Runtime adapter, Public API binding,
// submission, observation, or translation exists. The Runtime
// Public API remains the authoritative future boundary.
// ============================================================

#include <agent_kernel/agent/agent.hpp>
#include <agent_kernel/agent/runtime/runtime_interaction_port.hpp>
#include <agent_kernel/agent/validation/agent_boundary_validator.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <type_traits>

namespace ak::agent {
namespace {

// Negative API surface: the Phase 1 port exposes no concrete
// Runtime interaction operations (Phase 5 only).
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

TEST(RuntimeIsolation, PortIsContractOnly) {
    const RuntimeInteractionPort port;
    EXPECT_TRUE(port.IsContractOnly());
    EXPECT_EQ(std::string(port.RuntimePublicApiBoundary()), "Runtime Public API");
    EXPECT_EQ(port.ContractVersion(), 1);
}

TEST(RuntimeIsolation, AgentCarriesTheRuntimePort) {
    Agent agent(MakeAgentIdentity(1));
    EXPECT_TRUE(agent.RuntimePort().IsContractOnly());
    EXPECT_EQ(std::string(agent.RuntimePort().RuntimePublicApiBoundary()),
              "Runtime Public API");
}

TEST(RuntimeIsolation, PortExposesNoPhase5Operations) {
    // Phase 5 concrete operations must not exist in Phase 1.
    static_assert(!HasSubmitRuntimeRequest<RuntimeInteractionPort>::value,
                  "Phase 1 port must not submit Runtime requests");
    static_assert(!HasObserveRuntimeStatus<RuntimeInteractionPort>::value,
                  "Phase 1 port must not observe Runtime status");
    static_assert(!HasTranslateRuntimeRequest<RuntimeInteractionPort>::value,
                  "Phase 1 port must not translate Runtime requests");
}

TEST(RuntimeIsolation, Phase1HasNoConcreteRuntimeDependency) {
    static_assert(AgentBoundaryValidator::Phase1HasNoConcreteRuntimeDependency(),
                  "Phase 1 must be free of concrete Runtime dependency");
}

TEST(RuntimeIsolation, NoRuntimeTypeCrossesTheBoundary) {
    // Compile-time proof: this TU includes only Agent and
    // Foundation headers. The static boundary check
    // (check_agent_boundaries.cmake) scans every Agent header
    // and source for Runtime includes.
    const RuntimeInteractionPort port;
    EXPECT_TRUE(port.IsContractOnly());
}

}  // namespace
}  // namespace ak::agent
