// ============================================================
// P0R0006 — Runtime Walking Skeleton Demonstration
// ============================================================
// Executable end-to-end validation of the integrated Runtime
// Revision 2 architecture:
//
//   Runtime startup → initialization → Session creation →
//   Workflow creation → Task creation → Scheduler selection →
//   Capability resolution → Task execution → Event publication →
//   Workflow completion → Session completion → Runtime shutdown
//
// Build (from repository root):
//   cmake -S . -B build -DAK_BUILD_EXAMPLES=ON
//   cmake --build build --target walking_skeleton_demo
//   ./build/runtime/walking_skeleton_demo   (or .exe on Windows)
// ============================================================

#include <iostream>
#include <memory>
#include <string>
#include <vector>

#include <runtime.h>
#include <runtime_event.h>
#include <agent_kernel/session.hpp>
#include <agent_kernel/session/session_builder.hpp>
#include <agent_kernel/workflow.hpp>
#include <agent_kernel/task.hpp>
#include <agent_kernel/task/task_execution_descriptor.hpp>

namespace ak::runtime {

namespace {

std::string EventTypeName(ak::RuntimeEventType type) {
    using ak::RuntimeEventType;
    switch (type) {
        case RuntimeEventType::kTaskStarted:       return "TaskStarted";
        case RuntimeEventType::kTaskCompleted:     return "TaskCompleted";
        case RuntimeEventType::kTaskFailed:        return "TaskFailed";
        case RuntimeEventType::kWorkflowStarted:   return "WorkflowStarted";
        case RuntimeEventType::kWorkflowCompleted: return "WorkflowCompleted";
        case RuntimeEventType::kWorkflowFailed:    return "WorkflowFailed";
        case RuntimeEventType::kSessionStarted:    return "SessionStarted";
        case RuntimeEventType::kSessionCompleted:  return "SessionCompleted";
        case RuntimeEventType::kSessionFailed:     return "SessionFailed";
        default:                                   return "Unknown";
    }
}

std::string StateName(ak::KernelObjectState state) {
    using ak::KernelObjectState;
    switch (state) {
        case KernelObjectState::kCreated:     return "Created";
        case KernelObjectState::kInitialized: return "Initialized";
        case KernelObjectState::kReady:       return "Ready";
        case KernelObjectState::kRunning:     return "Running";
        case KernelObjectState::kSuspended:   return "Suspended";
        case KernelObjectState::kCompleted:   return "Completed";
        case KernelObjectState::kFailed:      return "Failed";
        case KernelObjectState::kDestroyed:   return "Destroyed";
        default:                              return "Unknown";
    }
}

ak::TaskExecutionDescriptor MakeDescriptor(const std::string& name) {
    ak::TaskExecutionDescriptor descriptor;
    descriptor.capability.name = name;
    return descriptor;
}

}  // namespace
}  // namespace ak::runtime

int main() {
    using namespace ak;
    using namespace ak::runtime;

    std::cout << "=== P0R0006 Runtime Walking Skeleton Demonstration ===\n";

    // 1. Runtime startup — construct the Runtime and its services.
    Runtime runtime;
    std::cout << "[1] Runtime startup: services constructed\n";

    // Register the Walking Skeleton capabilities through the
    // sanctioned Runtime public registration path (TASK 2 §14;
    // TASK 3.1 §16) with deterministic real invokers (C1).
    runtime.RegisterCapability("demo.echo", "local",
        [](const std::string& payload) { return "echo:" + payload; });
    runtime.RegisterCapability("demo.transform", "local",
        [](const std::string& payload) { return "transform:" + payload; });
    std::cout << "[2] Capabilities registered: demo.echo, demo.transform\n";

    // Attach EventBus observers to demonstrate event publication.
    auto& eventBus = runtime.GetEventBus();
    const auto observe = [&eventBus](RuntimeEventType type) {
        eventBus.Subscribe(type, [](const RuntimeEvent& event) {
            std::cout << "    EVENT " << EventTypeName(event.type)
                      << " [id=" << event.eventID
                      << " ts=" << event.timestamp
                      << " session=" << event.sessionID.Value()
                      << " workflow=" << event.workflowID.Value()
                      << " task=" << event.taskID.Value()
                      << "] " << event.message << "\n";
        });
    };
    observe(RuntimeEventType::kSessionStarted);
    observe(RuntimeEventType::kWorkflowStarted);
    observe(RuntimeEventType::kTaskStarted);
    observe(RuntimeEventType::kTaskCompleted);
    observe(RuntimeEventType::kWorkflowCompleted);
    observe(RuntimeEventType::kSessionCompleted);

    // 2. Session creation (canonical Session lifecycle).
    auto session = SessionBuilder()
        .WithID(SessionID(1))
        .WithName("WalkingSkeleton")
        .WithMaxWorkflows(4)
        .Build();
    session->Initialize();
    session->Activate();
    std::cout << "[3] Session created: state=" << StateName(session->GetState()) << "\n";

    // 3. Workflow creation (Session-owned Workflow).
    const WorkflowID workflowId = session->CreateWorkflow();
    Workflow* workflow = session->FindWorkflow(workflowId);
    std::cout << "[4] Workflow created: id=" << workflowId.Value() << "\n";

    // 4. Task creation with immutable execution descriptors.
    const TaskID taskA = workflow->AddTask(MakeDescriptor("demo.echo"));
    const TaskID taskB = workflow->AddTask(MakeDescriptor("demo.transform"));
    const TaskID taskC = workflow->AddTask(MakeDescriptor("demo.echo"));
    workflow->DefineDependency(taskA, taskB);
    workflow->DefineDependency(taskB, taskC);
    workflow->Validate();
    std::cout << "[5] Tasks created: " << workflow->GetTaskCount()
              << " (echo -> transform -> echo)\n";

    // 5. Execute the complete Runtime lifecycle.
    std::cout << "[6] Runtime Run() begins\n";
    const RuntimeResult result = runtime.Run(*session);
    std::cout << "[7] Runtime Run() finished: "
              << (result.IsSuccess() ? "Completed" : "Failed")
              << " workflows=" << result.workflowsCompleted << "/" << result.workflowsTotal
              << " tasks=" << result.tasksCompleted << "/" << result.tasksTotal << "\n";

    // 6. Runtime shutdown (canonical lifecycle completion).
    runtime.Stop();
    std::cout << "[8] Runtime shutdown: IsRunning="
              << (runtime.IsRunning() ? "true" : "false") << "\n";

    std::cout << "[9] Final states: session=" << StateName(session->GetState())
              << " workflow=" << StateName(workflow->GetState())
              << " task=" << StateName(workflow->FindTask(taskA)->GetState())
              << "/" << StateName(workflow->FindTask(taskB)->GetState())
              << "/" << StateName(workflow->FindTask(taskC)->GetState()) << "\n";

    std::cout << "=== Walking Skeleton demonstration complete ===\n";
    return result.IsSuccess() ? 0 : 1;
}