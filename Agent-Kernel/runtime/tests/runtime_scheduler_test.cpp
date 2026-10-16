#include <gtest/gtest.h>
#include <runtime_scheduler.h>
#include <agent_kernel/workflow/workflow_graph.hpp>

namespace ak::runtime {
namespace {

// Helper: linear graph A → B → C.
ak::WorkflowGraph BuildLinearGraph(ak::TaskID a, ak::TaskID b, ak::TaskID c) {
    ak::WorkflowGraph graph;
    graph.AddNode(a);
    graph.AddNode(b);
    graph.AddNode(c);
    graph.AddEdge(a, b);
    graph.AddEdge(b, c);
    return graph;
}

// Verifies that a decision selects the expected root task.
void ExpectTaskReady(const SchedulingDecision& d, ak::TaskID expected) {
    EXPECT_EQ(d.status, SchedulingStatus::kTaskReady);
    ASSERT_TRUE(d.HasTask());
    EXPECT_EQ(d.nextTask->Value(), expected.Value());
}

// Verifies that a decision has no task and the given status.
void ExpectNoTask(const SchedulingDecision& d, SchedulingStatus expected) {
    EXPECT_EQ(d.status, expected);
    EXPECT_FALSE(d.HasTask());
}

// ============================================================
// Construction
// ============================================================
TEST(SchedulerTest, DefaultConstructionSucceeds) {
    Scheduler scheduler;
    // No public state introspection — verified by Next() below.
    ak::WorkflowGraph empty;
    auto d = scheduler.Next(empty);
    EXPECT_EQ(d.status, SchedulingStatus::kWorkflowCompleted);
}

// ============================================================
// Attach / Detach (verified through behavioral outcomes)
// ============================================================
TEST(SchedulerTest, AttachedWorkflowParticipatesInScheduling) {
    Scheduler scheduler;
    scheduler.Attach(ak::WorkflowID(100));

    ak::WorkflowGraph graph;
    graph.AddNode(ak::TaskID(1));

    auto d = scheduler.Next(graph);
    ExpectTaskReady(d, ak::TaskID(1));
}

TEST(SchedulerTest, DetachedWorkflowDoesNotAffectScheduling) {
    Scheduler scheduler;
    scheduler.Attach(ak::WorkflowID(1));
    scheduler.Detach(ak::WorkflowID(1));

    // Scheduler still works on a graph passed to Next().
    // Attach/Detach tracks membership; Next() evaluates the graph.
    ak::WorkflowGraph graph;
    graph.AddNode(ak::TaskID(2));

    auto d = scheduler.Next(graph);
    // Even if no workflows are attached, Next(graph) evaluates the graph.
    EXPECT_EQ(d.status, SchedulingStatus::kTaskReady);
}

TEST(SchedulerTest, AttachDuplicateIsDeterministicBehavior) {
    Scheduler scheduler;
    scheduler.Attach(ak::WorkflowID(42));
    scheduler.Attach(ak::WorkflowID(42));

    ak::WorkflowGraph graph;
    graph.AddNode(ak::TaskID(1));

    auto d1 = scheduler.Next(graph);
    auto d2 = scheduler.Next(graph);
    EXPECT_EQ(d1.status, d2.status);
    EXPECT_EQ(d1.HasTask(), d2.HasTask());
}

TEST(SchedulerTest, ReattachAfterDetach) {
    Scheduler scheduler;
    scheduler.Attach(ak::WorkflowID(1));
    scheduler.Detach(ak::WorkflowID(1));
    scheduler.Attach(ak::WorkflowID(1));

    ak::WorkflowGraph graph;
    graph.AddNode(ak::TaskID(1));
    auto d = scheduler.Next(graph);
    ExpectTaskReady(d, ak::TaskID(1));
}

// ============================================================
// Next() — basic cases
// ============================================================
TEST(SchedulerTest, NextOnEmptyGraphReturnsWorkflowCompleted) {
    Scheduler scheduler;
    scheduler.Attach(ak::WorkflowID(1));

    ak::WorkflowGraph emptyGraph;
    ExpectNoTask(scheduler.Next(emptyGraph), SchedulingStatus::kWorkflowCompleted);
}

TEST(SchedulerTest, NextOnSingleNodeGraphReturnsTaskReady) {
    Scheduler scheduler;
    scheduler.Attach(ak::WorkflowID(1));

    ak::WorkflowGraph graph;
    graph.AddNode(ak::TaskID(1));

    ExpectTaskReady(scheduler.Next(graph), ak::TaskID(1));
}

// ============================================================
// Next() — dependency resolution
// ============================================================
TEST(SchedulerTest, NextReturnsRootTaskWhenNoDepsCompleted) {
    Scheduler scheduler;
    scheduler.Attach(ak::WorkflowID(1));
    auto graph = BuildLinearGraph(ak::TaskID(10), ak::TaskID(11), ak::TaskID(12));
    ExpectTaskReady(scheduler.Next(graph), ak::TaskID(10));
}

TEST(SchedulerTest, NextReturnsNextTaskAfterDependencyCompleted) {
    Scheduler scheduler;
    scheduler.Attach(ak::WorkflowID(1));
    auto graph = BuildLinearGraph(ak::TaskID(20), ak::TaskID(21), ak::TaskID(22));

    scheduler.NotifyCompleted(ak::TaskID(20));
    ExpectTaskReady(scheduler.Next(graph), ak::TaskID(21));
}

// ============================================================
// Next() — full completion
// ============================================================
TEST(SchedulerTest, NextReturnsWorkflowCompletedWhenAllTasksDone) {
    Scheduler scheduler;
    scheduler.Attach(ak::WorkflowID(1));
    auto graph = BuildLinearGraph(ak::TaskID(40), ak::TaskID(41), ak::TaskID(42));

    scheduler.NotifyCompleted(ak::TaskID(40));
    scheduler.NotifyCompleted(ak::TaskID(41));
    scheduler.NotifyCompleted(ak::TaskID(42));

    ExpectNoTask(scheduler.Next(graph), SchedulingStatus::kWorkflowCompleted);
}

// ============================================================
// NotifyCompleted / NotifyFailed (verified behaviorally)
// ============================================================
TEST(SchedulerTest, CompletedTaskNotReturnedAgain) {
    Scheduler scheduler;
    scheduler.Attach(ak::WorkflowID(1));
    auto graph = BuildLinearGraph(ak::TaskID(60), ak::TaskID(61), ak::TaskID(62));

    ExpectTaskReady(scheduler.Next(graph), ak::TaskID(60));
    scheduler.NotifyCompleted(ak::TaskID(60));

    ExpectTaskReady(scheduler.Next(graph), ak::TaskID(61));
    scheduler.NotifyCompleted(ak::TaskID(61));

    ExpectTaskReady(scheduler.Next(graph), ak::TaskID(62));
}

TEST(SchedulerTest, NotifyFailedTaskMakesWorkflowUnrecoverable) {
    Scheduler scheduler;
    scheduler.Attach(ak::WorkflowID(1));
    auto graph = BuildLinearGraph(ak::TaskID(50), ak::TaskID(51), ak::TaskID(52));

    scheduler.NotifyCompleted(ak::TaskID(50));
    scheduler.NotifyFailed(ak::TaskID(51));

    ExpectNoTask(scheduler.Next(graph), SchedulingStatus::kWorkflowFailed);
}

// ============================================================
// Deterministic behavior
// ============================================================
TEST(SchedulerTest, SameStateProducesSameDecision) {
    Scheduler s1, s2;
    s1.Attach(ak::WorkflowID(1));
    s2.Attach(ak::WorkflowID(1));

    auto g1 = BuildLinearGraph(ak::TaskID(70), ak::TaskID(71), ak::TaskID(72));
    auto g2 = BuildLinearGraph(ak::TaskID(70), ak::TaskID(71), ak::TaskID(72));

    auto d1 = s1.Next(g1);
    auto d2 = s2.Next(g2);

    EXPECT_EQ(d1.status, d2.status);
    EXPECT_EQ(d1.HasTask(), d2.HasTask());
    if (d1.HasTask()) {
        EXPECT_EQ(d1.nextTask->Value(), d2.nextTask->Value());
    }
}

// ============================================================
// P0R0002 scope: no execution, no capability, no events
// ============================================================
TEST(SchedulerTest, SchedulerProducesDecisionsWithoutSideEffects) {
    Scheduler scheduler;
    scheduler.Attach(ak::WorkflowID(1));

    ak::WorkflowGraph graph;
    graph.AddNode(ak::TaskID(1));

    auto d1 = scheduler.Next(graph);
    // No side-effects from calling Next() alone.
    auto d2 = scheduler.Next(graph);
    EXPECT_EQ(d1.status, d2.status);
    EXPECT_EQ(d1.HasTask(), d2.HasTask());
    if (d1.HasTask()) {
        EXPECT_EQ(d1.nextTask->Value(), d2.nextTask->Value());
    }
}

}  // namespace
}  // namespace ak::runtime