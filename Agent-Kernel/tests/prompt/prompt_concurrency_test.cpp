// ============================================================
// prompt_concurrency_test.cpp - P1-IS007 Rev1.1 Chapter 35
// ============================================================
// Concurrency tests: concurrent assembly of the same immutable
// PromptDefinition with independent requests (PRM-021,
// PRM-047, AC-021); no data races, no cross-request
// contamination, and deterministic result semantics
// (Chapter 18).
// ============================================================

#include <agent_kernel/prompt/prompt.hpp>
#include <agent_kernel/prompt/prompt_request.hpp>
#include <agent_kernel/prompt/prompt_result.hpp>

#include <gtest/gtest.h>

#include <atomic>
#include <cstddef>
#include <string>
#include <thread>
#include <vector>

namespace ak::prompt {
namespace {

Prompt BuildConcurrentPrompt() {
    return Prompt(PromptDefinition(
        PromptId("concurrent-prompt"), "1.0",
        {PromptSection(
             PromptSectionKind::kUserInput,
             {PromptComponent(PromptSectionKind::kUserInput,
                              "Input: {user_input}")}),
         PromptSection(
             PromptSectionKind::kContextMaterial,
             {PromptComponent(PromptSectionKind::kContextMaterial,
                              "Context: {context_snapshot}")})},
        {PromptVariable("user_input", PromptSectionKind::kUserInput, true),
         PromptVariable("context_snapshot",
                        PromptSectionKind::kContextMaterial, true)}));
}

PromptAssemblyRequest MakeRequest(const std::string& input) {
    return PromptAssemblyRequest(
        {PromptInputBinding("user_input", input),
         PromptInputBinding("context_snapshot", "shared context")});
}

TEST(PromptConcurrency, PRM_021_ConcurrentAssemblyIndependentRequests) {
    Prompt prompt = BuildConcurrentPrompt();
    constexpr std::size_t kThreadCount = 8;
    constexpr std::size_t kIterations = 200;
    std::atomic<std::size_t> failures{0};

    std::vector<std::thread> threads;
    threads.reserve(kThreadCount);
    for (std::size_t t = 0; t < kThreadCount; ++t) {
        threads.emplace_back([&prompt, t, &failures]() {
            for (std::size_t i = 0; i < kIterations; ++i) {
                const std::string input = "thread-" + std::to_string(t) +
                                          "-iter-" + std::to_string(i);
                const PromptAssemblyResult result =
                    prompt.Assembly().Assemble(MakeRequest(input));
                if (!result.Succeeded()) {
                    failures.fetch_add(1, std::memory_order_relaxed);
                    continue;
                }
                const std::vector<AssembledComponent>& components =
                    result.result->Components();
                if (components.size() != 2u ||
                    components[0].content != "Input: " + input ||
                    components[1].content != "Context: shared context") {
                    failures.fetch_add(1, std::memory_order_relaxed);
                }
            }
        });
    }
    for (std::thread& thread : threads) {
        thread.join();
    }
    EXPECT_EQ(failures.load(), 0u);
}

TEST(PromptConcurrency, PRM_047_ConcurrentReadOfImmutableDefinition) {
    Prompt prompt = BuildConcurrentPrompt();
    constexpr std::size_t kThreadCount = 4;
    constexpr std::size_t kIterations = 500;
    std::atomic<std::size_t> failures{0};

    std::vector<std::thread> threads;
    threads.reserve(kThreadCount);
    for (std::size_t t = 0; t < kThreadCount; ++t) {
        threads.emplace_back([&prompt, &failures]() {
            for (std::size_t i = 0; i < kIterations; ++i) {
                const PromptDefinition& definition = prompt.Definition();
                if (definition.Id() != PromptId("concurrent-prompt") ||
                    definition.Version() != "1.0" ||
                    definition.Sections().size() != 2u) {
                    failures.fetch_add(1, std::memory_order_relaxed);
                }
            }
        });
    }
    for (std::thread& thread : threads) {
        thread.join();
    }
    EXPECT_EQ(failures.load(), 0u);
}

TEST(PromptConcurrency, PRM_014_ConcurrentDeterministicResults) {
    Prompt prompt = BuildConcurrentPrompt();
    constexpr std::size_t kThreadCount = 4;
    constexpr std::size_t kIterations = 100;
    const std::string input = "fixed-input";
    const PromptAssemblyRequest reference_request = MakeRequest(input);
    const PromptAssemblyResult reference =
        prompt.Assembly().Assemble(reference_request);
    ASSERT_TRUE(reference.Succeeded());
    std::atomic<std::size_t> mismatches{0};

    std::vector<std::thread> threads;
    threads.reserve(kThreadCount);
    for (std::size_t t = 0; t < kThreadCount; ++t) {
        threads.emplace_back([&prompt, &reference, input, &mismatches]() {
            for (std::size_t i = 0; i < kIterations; ++i) {
                const PromptAssemblyResult result =
                    prompt.Assembly().Assemble(MakeRequest(input));
                if (!result.Succeeded()) {
                    mismatches.fetch_add(1, std::memory_order_relaxed);
                    continue;
                }
                const std::vector<AssembledComponent>& components =
                    result.result->Components();
                const std::vector<AssembledComponent>& expected =
                    reference.result->Components();
                if (components.size() != expected.size()) {
                    mismatches.fetch_add(1, std::memory_order_relaxed);
                    continue;
                }
                for (std::size_t j = 0; j < components.size(); ++j) {
                    if (components[j].content != expected[j].content) {
                        mismatches.fetch_add(1, std::memory_order_relaxed);
                        break;
                    }
                }
            }
        });
    }
    for (std::thread& thread : threads) {
        thread.join();
    }
    EXPECT_EQ(mismatches.load(), 0u);
}

}  // namespace
}  // namespace ak::prompt