// ============================================================
// execution_composition_test.cpp - P1-IS002 composition tests
// ============================================================
// AG-007: Agent owns execution composition coordination;
// execution composition is an Agent-owned representation that
// does NOT execute, schedule, or resolve Runtime behavior
// (P1-IS002 Chapter 14.3).
// ============================================================

#include <agent_kernel/agent/agent.hpp>
#include <agent_kernel/agent/execution/execution_composition.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <type_traits>

namespace ak::agent {
namespace {

// Negative API surface: execution composition must expose no
// Runtime execution behavior.
template <typename T, typename = void>
struct HasExecute : std::false_type {};
template <typename T>
struct HasExecute<T, std::void_t<decltype(std::declval<T&>().Execute())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasSubmit : std::false_type {};
template <typename T>
struct HasSubmit<T, std::void_t<decltype(std::declval<T&>().Submit())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasSchedule : std::false_type {};
template <typename T>
struct HasSchedule<T, std::void_t<decltype(std::declval<T&>().Schedule())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasResolveCapability : std::false_type {};
template <typename T>
struct HasResolveCapability<
    T, std::void_t<decltype(std::declval<T&>().ResolveCapability())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasPublishEvent : std::false_type {};
template <typename T>
struct HasPublishEvent<T, std::void_t<decltype(std::declval<T&>().PublishEvent())>>
    : std::true_type {};

TEST(ExecutionComposition, ComposesWorkflowAndTaskStructures) {
    ExecutionComposition composition;

    const std::uint64_t workflow_step = composition.AddStep(
        CompositionStep{0, CompositionStepKind::kWorkflowComposition,
                        "fetch workflow", {}, {}, {}});
    const std::uint64_t task_step = composition.AddStep(
        CompositionStep{0, CompositionStepKind::kTaskComposition,
                        "fetch task", {}, {}, {}});

    EXPECT_NE(workflow_step, 0);
    EXPECT_NE(task_step, 0);
    EXPECT_EQ(composition.StepCount(), 2);
    EXPECT_TRUE(composition.HasStep(workflow_step));
    EXPECT_TRUE(composition.HasStep(task_step));
}

TEST(ExecutionComposition, OrganizesDependenciesAndConstraints) {
    ExecutionComposition composition;
    const std::uint64_t a = composition.AddStep(
        CompositionStep{0, CompositionStepKind::kSequencing, "step a", {}, {}, {}});
    const std::uint64_t b = composition.AddStep(
        CompositionStep{0, CompositionStepKind::kSequencing, "step b", {}, {}, {}});

    EXPECT_TRUE(composition.AddDependency(b, a));
    EXPECT_TRUE(composition.SetConstraint(b, "must follow a"));
    EXPECT_TRUE(composition.Validate());
}

TEST(ExecutionComposition, RejectsInvalidDependencyEdges) {
    ExecutionComposition composition;
    const std::uint64_t a = composition.AddStep(
        CompositionStep{0, CompositionStepKind::kTaskComposition, "a", {}, {}, {}});
    const std::uint64_t b = composition.AddStep(
        CompositionStep{0, CompositionStepKind::kTaskComposition, "b", {}, {}, {}});

    // Self-dependency is rejected.
    EXPECT_FALSE(composition.AddDependency(a, a));
    // Dependency on a missing step is rejected.
    EXPECT_FALSE(composition.AddDependency(a, 999));
    // Duplicate edge is rejected.
    EXPECT_TRUE(composition.AddDependency(a, b));
    EXPECT_FALSE(composition.AddDependency(a, b));
}

TEST(ExecutionComposition, RejectsCycles) {
    ExecutionComposition composition;
    const std::uint64_t a = composition.AddStep(
        CompositionStep{0, CompositionStepKind::kTaskComposition, "a", {}, {}, {}});
    const std::uint64_t b = composition.AddStep(
        CompositionStep{0, CompositionStepKind::kTaskComposition, "b", {}, {}, {}});

    ASSERT_TRUE(composition.AddDependency(a, b));
    ASSERT_TRUE(composition.AddDependency(b, a));
    EXPECT_FALSE(composition.Validate());
}

TEST(ExecutionComposition, UnknownDependencyInvalidatesComposition) {
    ExecutionComposition dangling;
    CompositionStep step;
    step.id = 1;
    step.kind = CompositionStepKind::kSequencing;
    step.description = "a";
    step.dependencies.push_back(7);  // unknown step id
    [[maybe_unused]] const std::uint64_t dangling_step = dangling.AddStep(step);
    EXPECT_FALSE(dangling.Validate());
}

TEST(ExecutionComposition, CarriesExecutionMetadata) {
    ExecutionComposition composition;
    ak::KernelMetadata metadata;
    metadata.name = "composition-1";
    composition.SetExecutionMetadata(metadata);
    EXPECT_EQ(composition.GetExecutionMetadata().name, "composition-1");
}

TEST(ExecutionComposition, PerformsNoRuntimeBehavior) {
    // Compile-time proof that the representation exposes no
    // execution/scheduling/capability/event surface.
    static_assert(!HasExecute<ExecutionComposition>::value,
                  "execution composition must not execute");
    static_assert(!HasSubmit<ExecutionComposition>::value,
                  "execution composition must not submit");
    static_assert(!HasSchedule<ExecutionComposition>::value,
                  "execution composition must not schedule");
    static_assert(!HasResolveCapability<ExecutionComposition>::value,
                  "execution composition must not resolve capabilities");
    static_assert(!HasPublishEvent<ExecutionComposition>::value,
                  "execution composition must not publish events");
}

}  // namespace
}  // namespace ak::agent
