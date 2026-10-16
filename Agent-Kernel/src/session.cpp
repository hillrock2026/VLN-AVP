#include <agent_kernel/session.hpp>
#include <agent_kernel/workflow.hpp>

namespace {

ak::KernelObjectID::ValueType nextWorkflowId = 2000;

}

namespace ak {

Session::Session(SessionID id, SessionConfiguration config)
    : TypedKernelObject<Session, SessionID>(id),
      state_(KernelObjectState::kCreated),
      configuration_(std::move(config)) {}

Session::~Session() noexcept = default;
Session::Session(Session&&) noexcept = default;
Session& Session::operator=(Session&&) noexcept = default;

KernelObjectState Session::GetState() const noexcept {
    return state_;
}

const KernelMetadata& Session::GetMetadata() const noexcept {
    return metadata_;
}

void Session::SetMetadata(const KernelMetadata& metadata) {
    metadata_ = metadata;
}

const SessionConfiguration& Session::GetConfiguration() const noexcept {
    return configuration_;
}

void Session::Initialize() {
    if (state_ == KernelObjectState::kCreated) {
        state_ = KernelObjectState::kInitialized;
    }
}

void Session::Activate() {
    if (state_ == KernelObjectState::kInitialized) {
        state_ = KernelObjectState::kReady;
    }
}

void Session::Shutdown() {
    state_ = KernelObjectState::kCompleted;
}

void Session::Destroy() {
    state_ = KernelObjectState::kDestroyed;
    workflowRegistry_.Clear();
}

WorkflowID Session::CreateWorkflow() {
    WorkflowID id(++nextWorkflowId);
    WorkflowConfiguration config;
    auto workflow = std::make_unique<Workflow>(id, GetID(), std::move(config));
    workflowRegistry_.Register(id, std::move(workflow));
    return id;
}

void Session::DestroyWorkflow(WorkflowID id) {
    workflowRegistry_.Unregister(id);
}

Workflow* Session::FindWorkflow(WorkflowID id) const noexcept {
    return workflowRegistry_.Find(id);
}

bool Session::HasWorkflow(WorkflowID id) const noexcept {
    return workflowRegistry_.Contains(id);
}

std::size_t Session::GetWorkflowCount() const noexcept {
    return workflowRegistry_.Count();
}

WorkflowRegistry& Session::Workflows() {
    return workflowRegistry_;
}

const WorkflowRegistry& Session::Workflows() const {
    return workflowRegistry_;
}

void Session::AttachObserver(std::shared_ptr<ISessionObserver> observer) {
    observerRegistry_.Attach(std::move(observer));
}

void Session::DetachObserver(ISessionObserver* observer) {
    observerRegistry_.Detach(observer);
}

}  // namespace ak
