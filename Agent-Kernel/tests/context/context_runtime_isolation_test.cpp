// ============================================================
// context_runtime_isolation_test.cpp - P1-IS004 Runtime boundary
// ============================================================
// CTX-011 / CTX-012: Context is Runtime-independent; Phase 2 has
// no concrete Runtime integration (no adapter, binding,
// submission, observation, or translation). Runtime interaction
// is Agent-mediated only and belongs to Phase 5.
// ============================================================

#include <agent_kernel/context/context.hpp>
#include <agent_kernel/context/context_agent_contract.hpp>
#include <agent_kernel/context/context_boundary_validator.hpp>
#include <agent_kernel/context/context_services.hpp>

#include <gtest/gtest.h>

#include <type_traits>

#include "test_doubles.hpp"

namespace ak::context {
namespace {

// Negative API surface: no Phase 5 concrete Runtime operations
// may exist anywhere in the Context boundary.
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

TEST(ContextRuntimeIsolation, Phase2HasNoConcreteRuntimeDependency) {
    static_assert(ContextBoundaryValidator::Phase2HasNoConcreteRuntimeDependency(),
                  "Phase 2 Context must be free of concrete Runtime dependency");
}

TEST(ContextRuntimeIsolation, NoPhase5SurfaceOnContextBoundary) {
    static_assert(!HasSubmitRuntimeRequest<Context>::value,
                  "Context must not submit Runtime requests in Phase 2");
    static_assert(!HasObserveRuntimeStatus<Context>::value,
                  "Context must not observe Runtime status in Phase 2");
    static_assert(!HasTranslateRuntimeRequest<Context>::value,
                  "Context must not translate Runtime requests in Phase 2");
    static_assert(!HasBindRuntimePublicApi<Context>::value,
                  "Context must not bind the Runtime Public API in Phase 2");
}

TEST(ContextRuntimeIsolation, NoPhase5SurfaceOnServicesOrContract) {
    static_assert(!HasSubmitRuntimeRequest<ContextCreationService>::value);
    static_assert(!HasObserveRuntimeStatus<ContextCreationService>::value);
    static_assert(!HasTranslateRuntimeRequest<ContextCreationService>::value);

    static_assert(!HasSubmitRuntimeRequest<ContextAccessService>::value);
    static_assert(!HasObserveRuntimeStatus<ContextAccessService>::value);

    static_assert(!HasSubmitRuntimeRequest<ContextUpdateService>::value);
    static_assert(!HasObserveRuntimeStatus<ContextUpdateService>::value);

    static_assert(!HasSubmitRuntimeRequest<ContextCompositionService>::value);
    static_assert(!HasObserveRuntimeStatus<ContextCompositionService>::value);

    static_assert(!HasSubmitRuntimeRequest<ContextReleaseService>::value);
    static_assert(!HasObserveRuntimeStatus<ContextReleaseService>::value);

    static_assert(!HasSubmitRuntimeRequest<ContextAgentContract>::value);
    static_assert(!HasObserveRuntimeStatus<ContextAgentContract>::value);
    static_assert(!HasTranslateRuntimeRequest<ContextAgentContract>::value);
}

TEST(ContextRuntimeIsolation, TuIncludesNoRuntimeHeader) {
    // This TU includes only Context and Foundation headers; the
    // ContextBoundaryCheck CTest scans every Context header and
    // source for Runtime/subsystem includes and validates the
    // agent_kernel_context link set.
    Context context(MakeContextIdentity(1));
    EXPECT_TRUE(context.AgentContract().ContractName() == "Context");
}

}  // namespace
}  // namespace ak::context
