#include <agent_kernel/workflow.hpp>
#include <agent_kernel/task.hpp>
#include <algorithm>
#include <stdexcept>

namespace {

ak::KernelObjectID::ValueType nextTaskId = 1000;

}

namespace ak {

Workflow::Workflow(WorkflowID id, SessionID parentSession, WorkflowConfiguration config)
    : TypedKernelObject<Workflow, WorkflowID>(id),
      parentSession_(parentSession),
      state_(KernelObjectState::kCreated),
      configuration_(std::move(config)) {}

Workflow::~Workflow() noexcept = default;
Workflow::Workflow(Workflow&&) noexcept = default;
Workflow& Workflow::operator=(Workflow&&) noexcept = default;

SessionID Workflow::GetParentSessionID() const noexcept {
    return parentSession_;
}

KernelObjectState Workflow::GetState() const noexcept {
    return state_;
}

const KernelMetadata& Workflow::GetMetadata() const noexcept {
    return metadata_;
}

void Workflow::SetMetadata(const KernelMetadata& metadata) {
    metadata_ = metadata;
}

const WorkflowConfiguration& Workflow::GetConfiguration() const noexcept {
    return configuration_;
}

void Workflow::Initialize() {
    if (state_ == KernelObjectState::kCreated) {
        state_ = KernelObjectState::kInitialized;
    }
}

void Workflow::Activate() {
    if (state_ == KernelObjectState::kInitialized) {
        state_ = KernelObjectState::kReady;
    }
}

void Workflow::Start() {
    if (state_ == KernelObjectState::kReady) {
        state_ = KernelObjectState::kRunning;
    }
}

void Workflow::Complete() {
    if (state_ == KernelObjectState::kReady ||
        state_ == KernelObjectState::kRunning) {
        state_ = KernelObjectState::kCompleted;
    }
}

void Workflow::Cancel() {
    state_ = KernelObjectState::kFailed;
}

void Workflow::Destroy() {
    state_ = KernelObjectState::kDestroyed;
    taskRegistry_.Clear();
    graph_.Clear();
}

TaskID Workflow::AddTask() {
    TaskID id(++nextTaskId);
    auto task = std::make_unique<Task>(id, GetID());
    task->Initialize();
    taskRegistry_.Register(id, std::move(task));
    graph_.AddNode(id);
    return id;
}

TaskID Workflow::AddTask(const TaskExecutionDescriptor& descriptor) {
    TaskID id(++nextTaskId);
    auto task = std::make_unique<Task>(id, GetID(), descriptor);
    task->Initialize();
    taskRegistry_.Register(id, std::move(task));
    graph_.AddNode(id);
    return id;
}

void Workflow::RemoveTask(TaskID id) {
    graph_.RemoveNode(id);
    taskRegistry_.Unregister(id);
}

Task* Workflow::FindTask(TaskID id) const noexcept {
    return taskRegistry_.Find(id);
}

bool Workflow::HasTask(TaskID id) const noexcept {
    return taskRegistry_.Contains(id);
}

std::size_t Workflow::GetTaskCount() const noexcept {
    return taskRegistry_.Count();
}

void Workflow::DefineDependency(TaskID from, TaskID to) {
    graph_.AddEdge(from, to);
}

bool Workflow::Validate() {
    return graph_.Validate();
}

const WorkflowGraph& Workflow::Graph() const noexcept {
    return graph_;
}

TaskRegistry& Workflow::Tasks() {
    return taskRegistry_;
}

const TaskRegistry& Workflow::Tasks() const {
    return taskRegistry_;
}

void Workflow::AttachObserver(std::shared_ptr<IWorkflowObserver> observer) {
    observerRegistry_.Attach(std::move(observer));
}

void Workflow::DetachObserver(IWorkflowObserver* observer) {
    observerRegistry_.Detach(observer);
}

}  // namespace ak
