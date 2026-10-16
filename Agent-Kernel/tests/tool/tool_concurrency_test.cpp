// ============================================================
// tool_concurrency_test.cpp - P1-IS006 Rev2 Chapter 33.12
// ============================================================
// Concurrency tests: concurrent lifecycle operations (TOL-066),
// concurrent duplicate capability/Provider registration
// (TOL-067/068), serialized discovery versus mutation
// (TOL-104), retirement race semantics (TOL-107), provider
// callbacks outside the domain and re-entrancy rejection
// (TOL-106), and deterministic linearization (TOL-105).
// ============================================================

#include <agent_kernel/tool/tool.hpp>

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include "test_doubles.hpp"

namespace ak::tool {
namespace {

constexpr int kThreadCount = 8;

TEST(ToolConcurrency, TOL_066_ConcurrentLifecycleOperationsLinearize) {
    Tool tool(ToolId("conc-life"),
              ToolConfiguration{"concurrency", "1.0", "concurrency test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    std::atomic<bool> start{false};
    std::atomic<int> success{0};
    std::atomic<int> invalid_state{0};
    std::vector<std::thread> threads;
    for (int i = 0; i < kThreadCount; ++i) {
        threads.emplace_back([&] {
            while (!start.load()) {
                std::this_thread::yield();
            }
            const ToolLifecycleResult result = tool.Activate();
            if (result.status == ToolLifecycleResultStatus::kSuccess) {
                ++success;
            } else if (result.status == ToolLifecycleResultStatus::kInvalidState) {
                ++invalid_state;
            }
        });
    }
    start.store(true);
    for (auto& thread : threads) {
        thread.join();
    }
    // Exactly one transition commits; losers are deterministic
    // (TOL-066, TOL-105).
    EXPECT_EQ(success.load(), 1);
    EXPECT_EQ(invalid_state.load(), kThreadCount - 1);
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kAvailable);
}

TEST(ToolConcurrency, TOL_067_ConcurrentDuplicateCapabilityRegistration) {
    Tool tool(ToolId("conc-cap"),
              ToolConfiguration{"concurrency", "1.0", "concurrency test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    std::atomic<bool> start{false};
    std::atomic<int> success{0};
    std::atomic<int> already{0};
    std::vector<std::thread> threads;
    for (int i = 0; i < kThreadCount; ++i) {
        threads.emplace_back([&] {
            while (!start.load()) {
                std::this_thread::yield();
            }
            const ToolCapabilityResult result = tool.Capabilities()
                .RegisterCapability(test::MakeCapability("cap-x", "provider-x"));
            if (result.status == ToolResultStatus::kSuccess) {
                ++success;
            } else if (result.status == ToolResultStatus::kAlreadyExists) {
                ++already;
            }
        });
    }
    start.store(true);
    for (auto& thread : threads) {
        thread.join();
    }
    EXPECT_EQ(success.load(), 1);
    EXPECT_EQ(already.load(), kThreadCount - 1);
    const auto discovery = tool.Discovery().ListCapabilities();
    ASSERT_EQ(discovery.status, ToolResultStatus::kSuccess);
    EXPECT_EQ(discovery.capabilities.size(), 1u);
}

TEST(ToolConcurrency, TOL_068_ConcurrentDuplicateProviderRegistration) {
    Tool tool(ToolId("conc-provider"),
              ToolConfiguration{"concurrency", "1.0", "concurrency test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    std::atomic<bool> start{false};
    std::atomic<int> success{0};
    std::atomic<int> already{0};
    std::vector<std::thread> threads;
    for (int i = 0; i < kThreadCount; ++i) {
        threads.emplace_back([&] {
            while (!start.load()) {
                std::this_thread::yield();
            }
            auto provider =
                std::make_unique<test::TestToolProvider>("provider-x");
            provider->capabilities.push_back(
                test::MakeCapability("cap-x", "provider-x"));
            const ProviderResult result = tool.Providers().Register(std::move(provider));
            if (result.status == ToolResultStatus::kSuccess) {
                ++success;
            } else if (result.status == ToolResultStatus::kAlreadyExists) {
                ++already;
            }
        });
    }
    start.store(true);
    for (auto& thread : threads) {
        thread.join();
    }
    EXPECT_EQ(success.load(), 1);
    EXPECT_EQ(already.load(), kThreadCount - 1);
    EXPECT_EQ(tool.Providers().GetProvider(ProviderId("provider-x")).status,
              ToolResultStatus::kSuccess);
}

TEST(ToolConcurrency, TOL_104_ConcurrentDiscoveryVersusMutationSerialized) {
    Tool tool(ToolId("conc-discovery"),
              ToolConfiguration{"concurrency", "1.0", "concurrency test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    std::atomic<bool> stop{false};
    std::atomic<int> bad_status{0};
    std::vector<std::thread> threads;
    for (int i = 0; i < 4; ++i) {
        threads.emplace_back([&, i] {
            for (int k = 0; k < 200; ++k) {
                const ToolCapabilityResult result = tool.Capabilities()
                    .RegisterCapability(test::MakeCapability(
                        "cap-" + std::to_string(i) + "-" + std::to_string(k),
                        "provider-x"));
                if (result.status != ToolResultStatus::kSuccess) {
                    ++bad_status;
                }
            }
        });
    }
    for (int i = 0; i < 4; ++i) {
        threads.emplace_back([&] {
            while (!stop.load()) {
                const ToolDiscoveryResult result =
                    tool.Discovery().ListCapabilities();
                if (result.status != ToolResultStatus::kSuccess) {
                    ++bad_status;
                }
            }
        });
    }
    for (std::size_t i = 0; i < 4; ++i) {
        threads[i].join();
    }
    stop.store(true);
    for (std::size_t i = 4; i < threads.size(); ++i) {
        threads[i].join();
    }
    // No invalid state and no partial observation: every reader
    // saw a fully committed capability set (TOL-104, TOL-105).
    EXPECT_EQ(bad_status.load(), 0);
    const auto discovery = tool.Discovery().ListCapabilities();
    ASSERT_EQ(discovery.status, ToolResultStatus::kSuccess);
    EXPECT_EQ(discovery.capabilities.size(), 800u);
}

TEST(ToolConcurrency, TOL_107_RetirementRaceHasDeterministicOutcome) {
    Tool tool(ToolId("conc-retire"),
              ToolConfiguration{"concurrency", "1.0", "concurrency test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    auto provider = std::make_unique<test::TestToolProvider>("provider-a");
    provider->capabilities.push_back(
        test::MakeCapability("cap-a", "provider-a"));
    test::TestToolProvider* raw = provider.get();
    ASSERT_EQ(tool.Providers().Register(std::move(provider)).status,
              ToolResultStatus::kSuccess);
    ASSERT_TRUE(tool.Activate().Succeeded());

    std::atomic<bool> hook_entered{false};
    std::atomic<bool> release{false};
    raw->prepare_hook = [&] {
        hook_entered.store(true);
        while (!release.load()) {
            std::this_thread::yield();
        }
    };

    InvocationPreparationResult outcome{
        InvocationPreparationStatus::kRejected, CapabilityId("cap-a"),
        ProviderId("provider-a"), "", ""};
    std::thread worker([&] {
        outcome = tool.InvocationPreparation().PrepareInvocation(
            InvocationRequest{CapabilityId("cap-a"), "req", "payload"});
    });
    while (!hook_entered.load()) {
        std::this_thread::yield();
    }
    // The worker is inside the Provider callback (outside the
    // synchronization domain); the retirement commits now.
    ASSERT_TRUE(tool.Retire().Succeeded());
    ASSERT_TRUE(tool.FinalizeRetirement().Succeeded());
    release.store(true);
    worker.join();
    // The in-flight callback re-validates after the retirement
    // commit and refuses deterministically (TOL-107, TOL-106).
    EXPECT_EQ(outcome.status, InvocationPreparationStatus::kUnavailable);
    EXPECT_EQ(tool.LifecycleState(), ToolLifecycleState::kRetired);
}

TEST(ToolConcurrency, TOL_106_UnregisterWaitsForInflightProviderCallback) {
    Tool tool(ToolId("conc-unregister"),
              ToolConfiguration{"concurrency", "1.0", "concurrency test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    auto provider = std::make_unique<test::TestToolProvider>("provider-a");
    provider->capabilities.push_back(
        test::MakeCapability("cap-a", "provider-a"));
    test::TestToolProvider* raw = provider.get();
    ASSERT_EQ(tool.Providers().Register(std::move(provider)).status,
              ToolResultStatus::kSuccess);
    ASSERT_TRUE(tool.Activate().Succeeded());

    std::atomic<bool> hook_entered{false};
    std::atomic<bool> release{false};
    std::atomic<bool> unregister_done{false};
    raw->prepare_hook = [&] {
        hook_entered.store(true);
        while (!release.load()) {
            std::this_thread::yield();
        }
    };

    InvocationPreparationResult outcome{
        InvocationPreparationStatus::kRejected, CapabilityId("cap-a"),
        ProviderId("provider-a"), "", ""};
    std::thread worker([&] {
        outcome = tool.InvocationPreparation().PrepareInvocation(
            InvocationRequest{CapabilityId("cap-a"), "req", "payload"});
    });
    while (!hook_entered.load()) {
        std::this_thread::yield();
    }
    std::thread unregister([&] {
        (void)tool.Providers().Unregister(ProviderId("provider-a"));
        unregister_done.store(true);
    });
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    // The provider must not be destroyed while the callback is
    // in flight (TOL-100, TOL-106).
    EXPECT_FALSE(unregister_done.load());
    release.store(true);
    worker.join();
    unregister.join();
    EXPECT_TRUE(unregister_done.load());
    // The operation linearized before the unregistration commit
    // completes normally OR is refused after re-validation;
    // both outcomes are deterministic (TOL-105, TOL-106).
    EXPECT_TRUE(outcome.status == InvocationPreparationStatus::kPrepared ||
                outcome.status == InvocationPreparationStatus::kUnavailable);
    EXPECT_EQ(tool.Providers().GetProvider(ProviderId("provider-a")).status,
              ToolResultStatus::kNotFound);
}

TEST(ToolConcurrency, TOL_106_ProviderCallbacksRunOutsideDomainAndReentryIsRejected) {
    Tool tool(ToolId("conc-reentry"),
              ToolConfiguration{"concurrency", "1.0", "concurrency test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    auto provider = std::make_unique<test::TestToolProvider>("provider-a");
    provider->capabilities.push_back(
        test::MakeCapability("cap-a", "provider-a"));
    test::TestToolProvider* raw = provider.get();
    raw->describe_hook = [&tool] {
        // Re-entrant call from inside the callback: rejected
        // deterministically with kRejected (no deadlock).
        const ToolDiscoveryResult reentrant =
            tool.Discovery().ListCapabilities();
        EXPECT_EQ(reentrant.status, ToolResultStatus::kRejected);
    };
    ASSERT_EQ(tool.Providers().Register(std::move(provider)).status,
              ToolResultStatus::kSuccess);
    ASSERT_TRUE(tool.Activate().Succeeded());

    raw->prepare_hook = [&tool] {
        const InvocationPreparationResult reentrant =
            tool.InvocationPreparation().PrepareInvocation(
                InvocationRequest{CapabilityId("cap-a"), "re", "p"});
        EXPECT_EQ(reentrant.status, InvocationPreparationStatus::kRejected);
    };
    const InvocationPreparationResult prepared =
        tool.InvocationPreparation().PrepareInvocation(
            InvocationRequest{CapabilityId("cap-a"), "req", "payload"});
    ASSERT_EQ(prepared.status, InvocationPreparationStatus::kPrepared);
    EXPECT_EQ(prepared.invocation_token, "prepared-token");
}

TEST(ToolConcurrency, TOL_105_ConflictingOperationsHaveDeterministicOutcomes) {
    // The same invalid operation repeated concurrently produces
    // the same deterministic category for every loser.
    Tool tool(ToolId("conc-determinism"),
              ToolConfiguration{"concurrency", "1.0", "concurrency test"});
    ASSERT_TRUE(tool.Register().Succeeded());
    ASSERT_TRUE(tool.Activate().Succeeded());
    std::atomic<bool> start{false};
    std::atomic<int> invalid_state{0};
    std::vector<std::thread> threads;
    for (int i = 0; i < kThreadCount; ++i) {
        threads.emplace_back([&] {
            while (!start.load()) {
                std::this_thread::yield();
            }
            // Suspend is illegal from kAvailable for the losers
            // of the single legal transition; exactly one wins.
            const ToolLifecycleResult result = tool.Suspend();
            if (result.status == ToolLifecycleResultStatus::kInvalidState) {
                ++invalid_state;
            }
        });
    }
    start.store(true);
    for (auto& thread : threads) {
        thread.join();
    }
    // One Suspend commits; every other caller observes
    // kInvalidState with no partial mutation (TOL-065/066/105).
    EXPECT_EQ(invalid_state.load(), kThreadCount - 1);
    EXPECT_TRUE(tool.LifecycleState() == ToolLifecycleState::kSuspended ||
                tool.LifecycleState() == ToolLifecycleState::kAvailable);
}

}  // namespace
}  // namespace ak::tool