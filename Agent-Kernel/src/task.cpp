#include <agent_kernel/task.hpp>
#include <algorithm>

namespace ak {

Task::Task(TaskID id, WorkflowID parentWorkflow)
    : TypedKernelObject<Task, TaskID>(id),
      parentWorkflow_(parentWorkflow),
      state_(KernelObjectState::kCreated),
      executionDescriptor_()   // default empty
{
}

Task::Task(TaskID id, WorkflowID parentWorkflow, const TaskExecutionDescriptor& descriptor)
    : TypedKernelObject<Task, TaskID>(id),
      parentWorkflow_(parentWorkflow),
      state_(KernelObjectState::kCreated),
      executionDescriptor_(descriptor) {}


Task::~Task() noexcept = default;
Task::Task(Task&&) noexcept = default;
Task& Task::operator=(Task&&) noexcept = default;

WorkflowID Task::GetParentWorkflowID() const noexcept {
    return parentWorkflow_;
}

KernelObjectState Task::GetState() const noexcept {
    return state_;
}

const KernelMetadata& Task::GetMetadata() const noexcept {
    return metadata_;
}

void Task::SetMetadata(const KernelMetadata& metadata) {
    metadata_ = metadata;
}

const TaskContract& Task::GetContract() const noexcept {
    return contract_;
}

const TaskExecutionDescriptor& Task::GetExecutionDescriptor() const noexcept {
    return executionDescriptor_;
}

void Task::Initialize() {

    if (state_ == KernelObjectState::kCreated) {
        state_ = KernelObjectState::kReady;
    }
}

void Task::Reset() {
    state_ = KernelObjectState::kReady;
}

void Task::Destroy() {
    state_ = KernelObjectState::kDestroyed;
}

void Task::Complete() {
    if (state_ == KernelObjectState::kReady ||
        state_ == KernelObjectState::kRunning) {
        state_ = KernelObjectState::kCompleted;
    }
}


const std::vector<TaskDependency>& Task::GetDependencies() const noexcept {
    return dependencies_;
}

void Task::AttachObserver(std::shared_ptr<ITaskObserver> observer) {
    observerRegistry_.Attach(std::move(observer));
}

void Task::DetachObserver(ITaskObserver* observer) {
    observerRegistry_.Detach(observer);
}

}  // namespace ak
