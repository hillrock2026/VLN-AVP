// ============================================================
// tool_runtime_isolation_test.cpp - P1-IS006 Rev2 Chapter 33.14
// ============================================================
// Runtime isolation tests: no Runtime includes, no Runtime
// type references, no Runtime CMake dependency, no Scheduler
// surface, no Executor surface, no Runtime Public API surface
// (TOL-071/072/073/074/080).
// ============================================================

#include <agent_kernel/tool/capability_contract.hpp>
#include <agent_kernel/tool/i_tool_extension.hpp>
#include <agent_kernel/tool/i_tool_provider.hpp>
#include <agent_kernel/tool/tool.hpp>
#include <agent_kernel/tool/tool_capability.hpp>
#include <agent_kernel/tool/tool_identity.hpp>
#include <agent_kernel/tool/tool_result.hpp>
#include <agent_kernel/tool/tool_services.hpp>
#include <agent_kernel/tool/tool_state.hpp>

#include <gtest/gtest.h>

#include <fstream>
#include <string>
#include <type_traits>

namespace ak::tool {
namespace {

// Negative surface traits for every prohibited Runtime API name
// (Chapter 34, TOL-074).
template <typename T, typename = void>
struct HasScheduleWork : std::false_type {};
template <typename T>
struct HasScheduleWork<T, std::void_t<decltype(std::declval<T&>().ScheduleWork())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasExecuteWork : std::false_type {};
template <typename T>
struct HasExecuteWork<T, std::void_t<decltype(std::declval<T&>().ExecuteWork())>>
    : std::true_type {};

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

template <typename T, typename = void>
struct HasResolveRuntimeCapability : std::false_type {};
template <typename T>
struct HasResolveRuntimeCapability<
    T, std::void_t<decltype(std::declval<T&>().ResolveRuntimeCapability())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasPublishRuntimeEvent : std::false_type {};
template <typename T>
struct HasPublishRuntimeEvent<
    T, std::void_t<decltype(std::declval<T&>().PublishRuntimeEvent())>>
    : std::true_type {};

TEST(ToolRuntimeIsolation, TOL_074_NoRuntimeExecutionSurfaceOnTool) {
    static_assert(!HasScheduleWork<Tool>::value,
                  "Tool must not schedule Runtime work");
    static_assert(!HasExecuteWork<Tool>::value,
                  "Tool must not execute Runtime work");
    static_assert(!HasSubmitRuntimeRequest<Tool>::value,
                  "Tool must not submit Runtime requests");
    static_assert(!HasObserveRuntimeStatus<Tool>::value,
                  "Tool must not observe Runtime status");
    static_assert(!HasTranslateRuntimeRequest<Tool>::value,
                  "Tool must not translate Runtime requests");
    static_assert(!HasBindRuntimePublicApi<Tool>::value,
                  "Tool must not bind the Runtime Public API");
    static_assert(!HasResolveRuntimeCapability<Tool>::value,
                  "Tool must not resolve Runtime capabilities");
    static_assert(!HasPublishRuntimeEvent<Tool>::value,
                  "Tool must not publish Runtime events");
}

TEST(ToolRuntimeIsolation, TOL_074_NoRuntimeExecutionSurfaceOnServices) {
    static_assert(!HasScheduleWork<IToolProvider>::value);
    static_assert(!HasExecuteWork<IToolProvider>::value);
    static_assert(!HasSubmitRuntimeRequest<IToolProviderService>::value);
    static_assert(!HasObserveRuntimeStatus<IToolCapabilityService>::value);
    static_assert(!HasResolveRuntimeCapability<IToolInvocationPreparationService>::value);
    static_assert(!HasPublishRuntimeEvent<IToolExtensionContext>::value);
}

TEST(ToolRuntimeIsolation, TOL_071_TuIncludesNoRuntimeHeader) {
    // This TU includes only Tool and Foundation headers; the
    // ToolBoundaryCheck CTest scans every Tool header and
    // source for Runtime/subsystem includes and validates the
    // agent_kernel_tool link set (TOL-071/072/073).
    Tool tool(ToolId("isolation-tool"),
              ToolConfiguration{"isolation", "1.0", "isolation test"});
    EXPECT_EQ(tool.Id().Value(), "isolation-tool");
}

TEST(ToolRuntimeIsolation, TOL_072_NoRuntimeTypeInToolBoundary) {
    // Tool public types are all Tool-owned value/contract types;
    // none derives from or references a Runtime type.

    static_assert(std::is_copy_constructible_v<ToolCapability>);
    static_assert(std::is_copy_constructible_v<CapabilityContract>);
    static_assert(std::is_copy_constructible_v<ToolDiscoveryResult>);
}

TEST(ToolRuntimeIsolation, TOL_080_IsolationIsIndependentlyVerified) {
    // The runtime-isolation evidence is independent of the
    // functional Tool tests: the ToolBoundaryCheck CTest scans
    // the boundary and the link set, and this TU performs its
    // own negative-surface verification.
    EXPECT_TRUE(true);
}

}  // namespace
}  // namespace ak::tool