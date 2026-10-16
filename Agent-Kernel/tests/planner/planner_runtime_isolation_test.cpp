// ============================================================
// planner_runtime_isolation_test.cpp - P1-IS005 Runtime boundary
// ============================================================
// PLN-002/077: Phase 3 Planner is Runtime-independent; no
// Runtime request, adapter, Scheduler, Executor, Workflow, Task,
// or execution-composition surface exists on the Planner
// boundary; no Agent acknowledgement gate exists.
// ============================================================

#include <agent_kernel/planner/planner.hpp>
#include <agent_kernel/planner/planner_boundary_validator.hpp>
#include <agent_kernel/planner/planner_contracts.hpp>
#include <agent_kernel/planner/planner_services.hpp>
#include <agent_kernel/planner/planning_engine.hpp>

#include <gtest/gtest.h>

#include <type_traits>

#include "test_doubles.hpp"

namespace ak::planner {
namespace {

using test::PlannerTestFixture;

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
struct HasScheduleWork : std::false_type {};
template <typename T>
struct HasScheduleWork<
    T, std::void_t<decltype(std::declval<T&>().ScheduleWork())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasExecuteWork : std::false_type {};
template <typename T>
struct HasExecuteWork<
    T, std::void_t<decltype(std::declval<T&>().ExecuteWork())>>
    : std::true_type {};

TEST(PlannerRuntimeIsolation, Phase3HasNoConcreteRuntimeDependency) {
    static_assert(PlannerBoundaryValidator::Phase3HasNoConcreteRuntimeDependency(),
                  "Phase 3 Planner must be free of concrete Runtime dependency");
}

TEST(PlannerRuntimeIsolation, NoPhase5SurfaceOnPlannerBoundary) {
    static_assert(!HasSubmitRuntimeRequest<Planner>::value);
    static_assert(!HasObserveRuntimeStatus<Planner>::value);
    static_assert(!HasTranslateRuntimeRequest<Planner>::value);
    static_assert(!HasBindRuntimePublicApi<Planner>::value);
    static_assert(!HasScheduleWork<Planner>::value);
    static_assert(!HasExecuteWork<Planner>::value);

    static_assert(!HasSubmitRuntimeRequest<PlanningService>::value);
    static_assert(!HasObserveRuntimeStatus<PlanningService>::value);
    static_assert(!HasTranslateRuntimeRequest<PlanningService>::value);

    static_assert(!HasSubmitRuntimeRequest<LifecycleParticipationService>::value);
    static_assert(!HasSubmitRuntimeRequest<PlannerInspectionService>::value);
    static_assert(!HasSubmitRuntimeRequest<PlannerAgentContract>::value);
    static_assert(!HasSubmitRuntimeRequest<PlannerLifecycleContract>::value);
}

TEST(PlannerRuntimeIsolation, PlannerLifecycleRoundTripWithoutRuntime) {
    // This test executable links ONLY agent_kernel_planner and
    // agent_kernel_foundation (see tests/planner/CMakeLists.txt);
    // a full lifecycle round-trip proves Phase 3 independence.
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    fx.ActivatePlanner();

    const auto acceptance = fx.planner().AgentContract().Planning().Submit(
        fx.MakeRequest(1, "runtime-free"));
    ASSERT_TRUE(acceptance.IsAccepted());
    const auto completion = fx.planner().AgentContract().Planning().
        CompletePlanningExchange(acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    EXPECT_EQ(completion.result.artifact_view.payload, "runtime-free");
}

}  // namespace
}  // namespace ak::planner
