// ============================================================
// Agent Kernel — Session
// ============================================================
// Session represents one isolated execution environment.
//
// Responsibilities (AK0011 §3.2, AK0014):
// - Root Kernel Object — top of the ownership hierarchy
// - Owns all Workflow instances within its execution scope
// - Manages Workflow lifetime (create, destroy)
// - Provides Workflow lookup via WorkflowRegistry
// - Exposes SessionConfiguration (immutable construction parameters)
// - Exposes observability through ISessionObserver
//
// Session is the root Kernel Object. It is created via
// SessionBuilder and owned by Kernel Runtime (future).
//
// Foundation Layer: inherits TypedKernelObject<Session, SessionID>,
// composes ObserverRegistry, KernelMetadata, WorkflowRegistry,
// and SessionConfiguration.
//
// Session does NOT execute Workflows, schedule Tasks,
// dispatch events, or implement runtime policies.
// Those responsibilities belong to Scheduler, Executor,
// EventBus, and Runtime respectively.
// ============================================================

#pragma once

#include <memory>
#include <vector>

#include <agent_kernel/object_id.hpp>
#include <agent_kernel/state.hpp>
#include <agent_kernel/relationship.hpp>
#include <agent_kernel/foundation/kernel_object.hpp>
#include <agent_kernel/foundation/kernel_observer.hpp>
#include <agent_kernel/foundation/kernel_metadata.hpp>
#include <agent_kernel/foundation/kernel_contracts.hpp>
#include <agent_kernel/session/session_configuration.hpp>
#include <agent_kernel/session/workflow_registry.hpp>

namespace ak {

// ============================================================
// ISessionObserver
// ============================================================
class ISessionObserver : public KernelObserver {
public:
    ~ISessionObserver() noexcept override = default;

    virtual void OnWorkflowCreated(SessionID sessionId,
                                   WorkflowID workflowId) = 0;
    virtual void OnWorkflowDestroyed(SessionID sessionId,
                                     WorkflowID workflowId) = 0;
};

// ============================================================
// Session — root Kernel Object
// ============================================================
class Session : public TypedKernelObject<Session, SessionID> {
public:
    // -- Lifecycle --
    Session() = delete;
    Session(SessionID id, SessionConfiguration config);
    ~Session() noexcept override;

    Session(const Session&) = delete;
    Session& operator=(const Session&) = delete;
    Session(Session&&) noexcept;
    Session& operator=(Session&&) noexcept;

    // -- Identity (from TypedKernelObject) --
    using TypedKernelObject::GetID;
    using TypedKernelObject::GetIDValue;

    // -- State --
    [[nodiscard]] KernelObjectState GetState() const noexcept;

    // -- Metadata --
    [[nodiscard]] const KernelMetadata& GetMetadata() const noexcept;
    void SetMetadata(const KernelMetadata& metadata);

    // -- Configuration --
    [[nodiscard]] const SessionConfiguration& GetConfiguration() const noexcept;

    // -- Lifecycle operations --
    void Initialize();
    void Activate();
    void Shutdown();
    void Destroy();

    // -- Workflow management --
    WorkflowID CreateWorkflow();
    void DestroyWorkflow(WorkflowID id);
    [[nodiscard]] Workflow* FindWorkflow(WorkflowID id) const noexcept;
    [[nodiscard]] bool HasWorkflow(WorkflowID id) const noexcept;
    [[nodiscard]] std::size_t GetWorkflowCount() const noexcept;

    // -- Registry access --
    [[nodiscard]] WorkflowRegistry& Workflows();
    [[nodiscard]] const WorkflowRegistry& Workflows() const;

    // -- Observation --
    void AttachObserver(std::shared_ptr<ISessionObserver> observer);
    void DetachObserver(ISessionObserver* observer);

private:
    KernelObjectState state_;
    KernelMetadata metadata_;
    SessionConfiguration configuration_;
    WorkflowRegistry workflowRegistry_;
    ObserverRegistry observerRegistry_;
};

}  // namespace ak
