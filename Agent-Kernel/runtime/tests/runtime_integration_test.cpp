// ============================================================
// P0R0006 — Runtime Integration (Walking Skeleton) Tests
// ============================================================
// Validates the integrated Runtime Revision 2 execution path:
//
//   Session → Workflow → Task → Scheduler → CapabilityResolver →
//   Executor → EventBus → Task/Workflow/Session completion.
//
// Each Runtime component participates exclusively through its
// published contracts; no component is bypassed.
// ============================================================

#include <gtest/gtest.h>

#include <memory>
#include <string>
#include <vector>

#include <runtime.h>
#include <capability_resolver.h>
#include <runtime_event.h>
#include <agent_kernel/session.hpp>
#include <agent_kernel/session/session_configuration.hpp>
#include <agent_kernel/session/session_builder.hpp>
#include <agent_kernel/workflow.hpp>
#include <agent_kernel/task.hpp>
#include <agent_kernel/task/task_execution_descriptor.hpp>

namespace ak::runtime {

namespace {

std::unique_ptr<ak::Session> CreateReadySession() {
    auto session = ak::SessionBuilder()
        .WithID(ak::SessionID(1))
        .WithName("WalkingSkeleton_Test_Session")
        .WithMaxWorkflows(0)
        .Build();
    session->Initialize();
    session->Activate();
    return session;
}

ak::TaskExecutionDescriptor MakeDescriptor(const std::string& name) {
    ak::TaskExecutionDescriptor descriptor;
    descriptor.capability.name = name;
    return descriptor;
}

void RegisterDefaultCapabilities(Runtime& runtime) {
    // C1 (TASK 3.2 Conflict C): registration uses the sanctioned
    // public path (Runtime::RegisterCapability) with deterministic
    // real invokers. The private resolver test seam is not used.
    runtime.RegisterCapability("demo.echo", "local",
        [](const std::string& payload) { return "echo:" + payload; });
    runtime.RegisterCapability("demo.transform", "local",
        [](const std::string& payload) { return "transform:" + payload; });
}

// Builds a linear workflow A → B → C inside the session.
ak::Workflow* BuildLinearWorkflow(ak::Session& session,
                                  std::vector<ak::TaskID>& taskIds) {
    const ak::WorkflowID workflowId = session.CreateWorkflow();
    ak::Workflow* workflow = session.FindWorkflow(workflowId);

    const ak::TaskID a = workflow->AddTask(MakeDescriptor("demo.echo"));
    const ak::TaskID b = workflow->AddTask(MakeDescriptor("demo.transform"));
    const ak::TaskID c = workflow->AddTask(MakeDescriptor("demo.echo"));
    workflow->DefineDependency(a, b);
    workflow->DefineDependency(b, c);
    workflow->Validate();

    taskIds = {a, b, c};
    return workflow;
}

// ============================================================
// End-to-End Walking Skeleton
// ============================================================
TEST(RuntimeIntegrationTest, FullLifecycleCompletesEndToEnd) {
    Runtime runtime;
    RegisterDefaultCapabilities(runtime);

    auto session = CreateReadySession();
    std::vector<ak::TaskID> taskIds;
    ak::Workflow* workflow = BuildLinearWorkflow(*session, taskIds);

    RuntimeResult result = runtime.Run(*session);

    EXPECT_TRUE(result.IsSuccess());
    EXPECT_EQ(result.status, RuntimeStatus::kCompleted);
    EXPECT_EQ(result.workflowsTotal, 1u);
    EXPECT_EQ(result.workflowsCompleted, 1u);
    EXPECT_EQ(result.workflowsFailed, 0u);
    EXPECT_EQ(result.tasksTotal, 3u);
    EXPECT_EQ(result.tasksCompleted, 3u);
    EXPECT_EQ(result.tasksFailed, 0u);

    // Lifecycle states: Session → Completed, Workflow → Completed,
    // every Task → Completed.
    EXPECT_EQ(session->GetState(), ak::KernelObjectState::kCompleted);
    EXPECT_EQ(workflow->GetState(), ak::KernelObjectState::kCompleted);
    EXPECT_EQ(workflow->FindTask(taskIds[0])->GetState(),
              ak::KernelObjectState::kCompleted);
    EXPECT_EQ(workflow->FindTask(taskIds[1])->GetState(),
              ak::KernelObjectState::kCompleted);
    EXPECT_EQ(workflow->FindTask(taskIds[2])->GetState(),
              ak::KernelObjectState::kCompleted);

    // Runtime remains available (service semantics) until Stop().
    EXPECT_TRUE(runtime.IsRunning());
    runtime.Stop();
    EXPECT_FALSE(runtime.IsRunning());
}

// ============================================================
// Event publication follows the canonical Runtime flow
// ============================================================
TEST(RuntimeIntegrationTest, EventSequenceFollowsCanonicalFlow) {
    Runtime runtime;
    RegisterDefaultCapabilities(runtime);

    std::vector<ak::RuntimeEventType> events;
    auto& bus = runtime.GetEventBus();
    const ak::RuntimeEventType subscribedTypes[] = {
        ak::RuntimeEventType::kSessionStarted,
        ak::RuntimeEventType::kWorkflowStarted,
        ak::RuntimeEventType::kTaskStarted,
        ak::RuntimeEventType::kTaskCompleted,
        ak::RuntimeEventType::kWorkflowCompleted,
        ak::RuntimeEventType::kSessionCompleted,
    };
    for (const ak::RuntimeEventType type : subscribedTypes) {
        bus.Subscribe(type,
            [&events, type](const ak::RuntimeEvent&) {
                events.push_back(type);
            });
    }

    auto session = CreateReadySession();
    std::vector<ak::TaskID> taskIds;
    BuildLinearWorkflow(*session, taskIds);

    RuntimeResult result = runtime.Run(*session);
    ASSERT_TRUE(result.IsSuccess());

    const std::vector<ak::RuntimeEventType> expected = {
        ak::RuntimeEventType::kSessionStarted,
        ak::RuntimeEventType::kWorkflowStarted,
        ak::RuntimeEventType::kTaskStarted,
        ak::RuntimeEventType::kTaskCompleted,
        ak::RuntimeEventType::kTaskStarted,
        ak::RuntimeEventType::kTaskCompleted,
        ak::RuntimeEventType::kTaskStarted,
        ak::RuntimeEventType::kTaskCompleted,
        ak::RuntimeEventType::kWorkflowCompleted,
        ak::RuntimeEventType::kSessionCompleted,
    };
    EXPECT_EQ(events, expected);
}

// ============================================================
// Dependency ordering is preserved by the Scheduler
// ============================================================
TEST(RuntimeIntegrationTest, TaskDependenciesRespectExecutionOrder) {
    Runtime runtime;
    RegisterDefaultCapabilities(runtime);

    std::vector<ak::TaskID> startedTasks;
    runtime.GetEventBus().Subscribe(ak::RuntimeEventType::kTaskStarted,
        [&startedTasks](const ak::RuntimeEvent& event) {
            startedTasks.push_back(event.taskID);
        });

    auto session = CreateReadySession();
    std::vector<ak::TaskID> taskIds;
    BuildLinearWorkflow(*session, taskIds);

    RuntimeResult result = runtime.Run(*session);
    ASSERT_TRUE(result.IsSuccess());
    ASSERT_EQ(startedTasks.size(), 3u);

    // Linear dependency A → B → C: execution order is A, B, C.
    EXPECT_EQ(startedTasks[0], taskIds[0]);
    EXPECT_EQ(startedTasks[1], taskIds[1]);
    EXPECT_EQ(startedTasks[2], taskIds[2]);
}

// ============================================================
// Unresolvable capability → task/workflow failure
// ============================================================
TEST(RuntimeIntegrationTest, UnresolvableCapabilityFailsTaskAndWorkflow) {
    Runtime runtime;
    // Intentionally NO capabilities registered.

    bool taskFailed = false;
    bool workflowFailed = false;
    runtime.GetEventBus().Subscribe(ak::RuntimeEventType::kTaskFailed,
        [&taskFailed](const ak::RuntimeEvent&) { taskFailed = true; });
    runtime.GetEventBus().Subscribe(ak::RuntimeEventType::kWorkflowFailed,
        [&workflowFailed](const ak::RuntimeEvent&) { workflowFailed = true; });

    auto session = CreateReadySession();
    std::vector<ak::TaskID> taskIds;
    ak::Workflow* workflow = BuildLinearWorkflow(*session, taskIds);

    RuntimeResult result = runtime.Run(*session);

    EXPECT_FALSE(result.IsSuccess());
    EXPECT_EQ(result.status, RuntimeStatus::kFailed);
    EXPECT_EQ(result.tasksTotal, 1u);
    EXPECT_EQ(result.tasksFailed, 1u);
    EXPECT_EQ(result.tasksCompleted, 0u);
    EXPECT_EQ(result.workflowsTotal, 1u);
    EXPECT_EQ(result.workflowsFailed, 1u);
    EXPECT_EQ(result.workflowsCompleted, 0u);

    EXPECT_TRUE(taskFailed);
    EXPECT_TRUE(workflowFailed);

    // Workflow failed; the uncompleted Task remains non-terminal.
    EXPECT_EQ(workflow->GetState(), ak::KernelObjectState::kFailed);
    EXPECT_NE(workflow->FindTask(taskIds[0])->GetState(),
              ak::KernelObjectState::kCompleted);

    // The Session completes as a container even when workflows fail.
    EXPECT_EQ(session->GetState(), ak::KernelObjectState::kCompleted);
}

// ============================================================
// Multiple workflows all participate in execution
// ============================================================
TEST(RuntimeIntegrationTest, MultipleWorkflowsAllExecute) {
    Runtime runtime;
    RegisterDefaultCapabilities(runtime);

    auto session = CreateReadySession();

    ak::WorkflowID workflow1Id = session->CreateWorkflow();
    ak::Workflow* workflow1 = session->FindWorkflow(workflow1Id);
    workflow1->AddTask(MakeDescriptor("demo.echo"));

    ak::WorkflowID workflow2Id = session->CreateWorkflow();
    ak::Workflow* workflow2 = session->FindWorkflow(workflow2Id);
    workflow2->AddTask(MakeDescriptor("demo.transform"));

    RuntimeResult result = runtime.Run(*session);

    EXPECT_TRUE(result.IsSuccess());
    EXPECT_EQ(result.workflowsTotal, 2u);
    EXPECT_EQ(result.workflowsCompleted, 2u);
    EXPECT_EQ(result.workflowsFailed, 0u);
    EXPECT_EQ(result.tasksTotal, 2u);
    EXPECT_EQ(result.tasksCompleted, 2u);
    EXPECT_EQ(result.tasksFailed, 0u);

    EXPECT_EQ(workflow1->GetState(), ak::KernelObjectState::kCompleted);
    EXPECT_EQ(workflow2->GetState(), ak::KernelObjectState::kCompleted);
}

// ============================================================
// Deterministic execution — identical inputs, identical events
// ============================================================
TEST(RuntimeIntegrationTest, ExecutionIsDeterministic) {
    auto collectEvents = []() {
        Runtime runtime;
        RegisterDefaultCapabilities(runtime);

        std::vector<ak::RuntimeEventType> events;
        auto& bus = runtime.GetEventBus();
        const ak::RuntimeEventType subscribedTypes[] = {
            ak::RuntimeEventType::kSessionStarted,
            ak::RuntimeEventType::kWorkflowStarted,
            ak::RuntimeEventType::kTaskStarted,
            ak::RuntimeEventType::kTaskCompleted,
            ak::RuntimeEventType::kWorkflowCompleted,
            ak::RuntimeEventType::kSessionCompleted,
        };
        for (const ak::RuntimeEventType type : subscribedTypes) {
            bus.Subscribe(type,
                [&events, type](const ak::RuntimeEvent&) {
                    events.push_back(type);
                });
        }

        auto session = CreateReadySession();
        std::vector<ak::TaskID> taskIds;
        BuildLinearWorkflow(*session, taskIds);

        RuntimeResult result = runtime.Run(*session);
        EXPECT_TRUE(result.IsSuccess());
        return events;
    };

    const std::vector<ak::RuntimeEventType> first = collectEvents();
    const std::vector<ak::RuntimeEventType> second = collectEvents();

    ASSERT_EQ(first.size(), 10u);
    EXPECT_EQ(first, second);
}

}  // namespace
}  // namespace ak::runtime