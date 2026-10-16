// ============================================================
// planner_exactly_once_test.cpp - P1-IS005 exactly-once
// ============================================================
// PLN-038/066/071/075/076: CompletePlanningExchange is the sole
// delivery path; one terminal result per accepted exchange;
// duplicate/concurrent completion produces no second result;
// single serialization boundary.
// ============================================================

#include <agent_kernel/planner/planner.hpp>
#include <agent_kernel/planner/planning_engine.hpp>

#include <gtest/gtest.h>

#include <atomic>
#include <thread>
#include <type_traits>
#include <utility>
#include <vector>

#include "test_doubles.hpp"

namespace ak::planner {
namespace {

using test::PlannerTestFixture;
using test::StagedPlanningEngine;
using test::ThrowingPlanningEngine;
using test::FailingPlanningEngine;

TEST(PlannerExactlyOnce, DuplicateCompletionProducesNoSecondResult) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());

    const auto first = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    ASSERT_TRUE(first.IsSuccess());

    const auto duplicate = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    EXPECT_EQ(duplicate.status, PlanningCompletionStatus::kRejectedDuplicate);
    EXPECT_FALSE(duplicate.HasResult());

    // The previously delivered result remains Agent-owned and
    // readable.
    EXPECT_TRUE(first.IsSuccess());
    EXPECT_TRUE(first.result.IsValid());
    EXPECT_EQ(planner.OpenExchangeCount(), 0);
}

TEST(PlannerExactlyOnce, PendingCompletionPreservesExchangeUntilOutcomeReady) {
    StagedPlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());

    // Outcome not ready: kPending, exchange preserved, outcome not
    // consumed.
    const auto pending1 = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    EXPECT_EQ(pending1.status, PlanningCompletionStatus::kPending);
    EXPECT_FALSE(pending1.HasResult());
    EXPECT_EQ(planner.OpenExchangeCount(), 1);

    const auto pending2 = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    EXPECT_EQ(pending2.status, PlanningCompletionStatus::kPending);

    // Outcome becomes ready; the next attempt linearizes exactly
    // once.
    engine.MarkReady(fx.PrimarySessionId(), acceptance.request_id);
    const auto success = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    ASSERT_TRUE(success.IsSuccess());
    EXPECT_TRUE(success.HasResult());
    EXPECT_EQ(planner.OpenExchangeCount(), 0);

    const auto duplicate = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    EXPECT_EQ(duplicate.status, PlanningCompletionStatus::kRejectedDuplicate);
}

TEST(PlannerExactlyOnce, CompletionWhileSuspendedReturnsKSuspended) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());
    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Suspend().IsAccepted());

    const auto suspended = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    EXPECT_EQ(suspended.status, PlanningCompletionStatus::kSuspended);
    EXPECT_FALSE(suspended.HasResult());
    EXPECT_EQ(planner.OpenExchangeCount(), 1);

    // Resume; the exchange completes with exactly one result.
    ASSERT_TRUE(planner.LifecycleContract().Lifecycle().Resume().IsAccepted());
    const auto success = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    ASSERT_TRUE(success.IsSuccess());
    EXPECT_EQ(planner.OpenExchangeCount(), 0);
}

TEST(PlannerExactlyOnce, EngineContractIsNoexceptAndFailureIsDeterministic) {
    // The engine contract is noexcept (Chapter 11.1/11.3). A
    // genuine noexcept violation terminates the process per C++
    // semantics before any catch can observe it, so the throwing
    // double documents the boundary and is never invoked here.
    static_assert(noexcept(std::declval<IPlanningEngine&>().Outcome(
                      std::declval<const PlannerSessionId&>(),
                      std::declval<const PlanningRequest&>())),
                  "IPlanningEngine::Outcome SHALL be noexcept");

    // The catchable deterministic completion-failure path: a
    // failure outcome produces exactly one terminal kFailed
    // result, retires the exchange, and never escapes as an
    // exception to the caller.
    FailingPlanningEngine failing_engine;
    PlannerTestFixture fx(failing_engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());

    const auto completion = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    EXPECT_TRUE(completion.HasResult());
    EXPECT_EQ(completion.result.status, PlanningResultStatus::kFailed);
    EXPECT_EQ(planner.OpenExchangeCount(), 0);

    // Exactly-once holds for the failure path too.
    const auto duplicate = planner.AgentContract().Planning().CompletePlanningExchange(
        acceptance.request_id);
    EXPECT_EQ(duplicate.status, PlanningCompletionStatus::kRejectedDuplicate);
}

TEST(PlannerExactlyOnce, ConcurrentCompletionLinearizesExactlyOnce) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    const auto acceptance = planner.AgentContract().Planning().Submit(fx.MakeRequest(1));
    ASSERT_TRUE(acceptance.IsAccepted());
    const PlanningRequestId request_id = acceptance.request_id;

    constexpr int kThreads = 8;
    std::atomic<int> successes{0};
    std::vector<std::thread> threads;
    threads.reserve(kThreads);
    for (int i = 0; i < kThreads; ++i) {
        threads.emplace_back([&]() {
            const auto completion =
                planner.AgentContract().Planning().CompletePlanningExchange(request_id);
            if (completion.status == PlanningCompletionStatus::kSuccess) {
                successes.fetch_add(1, std::memory_order_relaxed);
            }
        });
    }
    for (auto& thread : threads) {
        thread.join();
    }

    EXPECT_EQ(successes.load(std::memory_order_relaxed), 1);
    EXPECT_EQ(planner.OpenExchangeCount(), 0);
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kReady);
}

TEST(PlannerExactlyOnce, ConcurrentSubmissionAcceptsAllDistinctRequests) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    constexpr int kThreads = 8;
    std::atomic<int> accepted{0};
    std::vector<std::thread> threads;
    threads.reserve(kThreads);
    for (int i = 1; i <= kThreads; ++i) {
        threads.emplace_back([&, i]() {
            const auto acceptance =
                planner.AgentContract().Planning().Submit(fx.MakeRequest(i));
            if (acceptance.IsAccepted()) {
                accepted.fetch_add(1, std::memory_order_relaxed);
            }
        });
    }
    for (auto& thread : threads) {
        thread.join();
    }

    EXPECT_EQ(accepted.load(std::memory_order_relaxed), kThreads);
    EXPECT_EQ(planner.OpenExchangeCount(), static_cast<std::size_t>(kThreads));
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kPlanning);

    for (int i = 1; i <= kThreads; ++i) {
        const auto completion = planner.AgentContract().Planning().CompletePlanningExchange(
            MakePlanningRequestId(i));
        EXPECT_EQ(completion.status, PlanningCompletionStatus::kSuccess);
    }
    EXPECT_EQ(planner.OpenExchangeCount(), 0);
    EXPECT_EQ(planner.GetLifecycleState(), PlannerLifecycleState::kReady);
}

TEST(PlannerExactlyOnce, SubmitCompleteTerminateRacePreservesInvariants) {
    ImmediatePlanningEngine engine;
    PlannerTestFixture fx(engine);
    Planner& planner = fx.planner();
    fx.ActivatePlanner();

    constexpr int kThreads = 4;
    std::vector<std::thread> threads;
    threads.reserve(kThreads + 1);
    for (int i = 1; i <= kThreads; ++i) {
        threads.emplace_back([&, i]() {
            const auto acceptance =
                planner.AgentContract().Planning().Submit(fx.MakeRequest(i));
            if (acceptance.IsAccepted()) {
                const auto completion = planner.AgentContract().Planning().
                    CompletePlanningExchange(acceptance.request_id);
                static_cast<void>(completion);
            }
        });
    }
    threads.emplace_back([&]() {
        static_cast<void>(planner.LifecycleContract().Lifecycle().Terminate());
    });
    for (auto& thread : threads) {
        thread.join();
    }

    // In every interleaving: exactly-once holds, and no exchange
    // is left open at Terminated.
    const PlannerState state = planner.GetState();
    EXPECT_TRUE(state.lifecycle == PlannerLifecycleState::kReady ||
                state.lifecycle == PlannerLifecycleState::kTerminated);
    if (state.lifecycle == PlannerLifecycleState::kTerminated) {
        EXPECT_EQ(state.open_exchange_count, 0);
        EXPECT_EQ(state.session_count, 0);
    }
}

// Negative API surface: no second result-delivery channel
// (outbox/sink/callback/post-terminal retrieval) exists on the
// Planner boundary.
template <typename T, typename = void>
struct HasRetrieveResult : std::false_type {};
template <typename T>
struct HasRetrieveResult<
    T, std::void_t<decltype(std::declval<T&>().RetrieveResult(
           std::declval<const PlanningRequestId&>()))>> : std::true_type {};

TEST(PlannerExactlyOnce, NoSecondDeliveryChannelExists) {
    // CompletePlanningExchange is the ONLY result-delivery path:
    // the Planner boundary exposes no outbox/sink/callback/
    // retrieval API.
    static_assert(!HasRetrieveResult<Planner>::value);
    static_assert(!HasRetrieveResult<PlanningService>::value);
    static_assert(!HasRetrieveResult<PlannerAgentContract>::value);
}

}  // namespace
}  // namespace ak::planner
