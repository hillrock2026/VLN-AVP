#pragma once

// ============================================================
// P0R0001 / P0R0002 / P0R0003 / P0R0004 / P0R0005 — Runtime Core
// ============================================================
// Main Runtime class — the root orchestrator of the Runtime Layer.
//
// P0R0001: Runtime object with lifecycle management.
// P0R0002: Scheduler integration.
// P0R0003: Executor integration.
// P0R0004: Capability Resolver integration.
// P0R0005: Event Bus integration.
//
// Conforms to AK0030-I4 (Runtime Public API Specification).
// ============================================================

#include <cstdint>
#include <optional>
#include <unordered_map>
#include <memory>
#include <string>

#include <agent_kernel/object_id.hpp>
#include <agent_kernel/executor/execution_result.hpp>

#include <runtime_configuration.h>
#include <runtime_state_machine.h>
#include <runtime_lifecycle_manager.h>
#include <runtime_scheduler.h>
#include <runtime_executor.h>
#include <capability_resolver.h>
#include <event_bus.h>

namespace ak {

class Session;

}  // namespace ak

namespace ak::runtime {

// ============================================================
// RuntimeStatus — Aggregate execution outcome
// ============================================================
enum class RuntimeStatus : std::uint8_t {
    kCompleted,
    kPartial,
    kFailed,
    kInvalidSession,
    kCancelled,
    kInternalError
};

// ============================================================
// RuntimeResult — Return type for Runtime::Run()
// ============================================================
struct RuntimeResult {
    RuntimeStatus status = RuntimeStatus::kCompleted;
    std::string message;

    std::size_t workflowsTotal = 0;
    std::size_t workflowsCompleted = 0;
    std::size_t workflowsFailed = 0;

    std::size_t tasksTotal = 0;
    std::size_t tasksCompleted = 0;
    std::size_t tasksFailed = 0;

    [[nodiscard]] bool IsSuccess() const noexcept {
        return status == RuntimeStatus::kCompleted;
    }
};

// ============================================================
// Runtime — Runtime Core class
// ============================================================
// Orchestrates all Runtime components:
//   - Scheduler (P0R0002)
//   - Executor  (P0R0003)
//   - CapabilityResolver (P0R0004)
//   - EventBus  (P0R0005)
//
// Usage:
//   Runtime runtime;
//   auto session = ...;
//   RuntimeResult result = runtime.Run(session);
class Runtime {
public:
    Runtime();
    ~Runtime();

    Runtime(const Runtime&) = delete;
    Runtime& operator=(const Runtime&) = delete;
    Runtime(Runtime&&) = delete;
    Runtime& operator=(Runtime&&) = delete;

    // ---- Execution ----
    RuntimeResult Run(ak::Session& session);
    void Stop();
    [[nodiscard]] bool IsRunning() const noexcept;


    // ---- TASK 2 CC-4a Minimum Runtime Public API Extensions ----

    // Capability registration (TASK 2 §14; TASK 3.1 §16): the
    // sanctioned production registration path. The Agent never
    // calls this directly; the adapter / integration bootstrap
    // calls it. Duplicate names overwrite deterministically.
    void RegisterCapability(const std::string& name,
                            const std::string& provider,
                            ak::CapabilityInvoker invoker);

    // Deterministic pre-check: is a capability registered?
    [[nodiscard]] bool HasCapability(const std::string& name) const;

    // Per-invocation result retrieval (TASK 2 §17; TASK 3.1 §9.4):
    // returns the ExecutionResult belonging to request_id, or
    // nullopt when absent. The store is cleared at the start of
    // each Run.
    [[nodiscard]] std::optional<ak::ExecutionResult>
    GetInvocationResult(const std::string& request_id) const;

    // ---- Component Access ----
    // Scheduler (P0R0002), Executor (P0R0003),
    // CapabilityResolver (P0R0004), EventBus (P0R0005).
    [[nodiscard]] Scheduler& GetScheduler() noexcept;
    [[nodiscard]] Executor& GetExecutor() noexcept;
    [[nodiscard]] CapabilityResolver& GetResolver() noexcept;
    [[nodiscard]] EventBus& GetEventBus() noexcept;

private:
    // Publish a Runtime lifecycle event through the canonical EventBus
    // (AK0034 — Runtime Event Bus is the exclusive event propagation mechanism).
    void PublishRuntimeEvent(ak::RuntimeEventType type,
                             const ak::TaskID& taskId,
                             const ak::WorkflowID& workflowId,
                             const ak::SessionID& sessionId,
                             std::string message);

    RuntimeConfiguration config_;
    RuntimeStateMachine stateMachine_;
    RuntimeLifecycleManager lifecycleManager_;

    Scheduler scheduler_;
    Executor executor_;
    CapabilityResolver resolver_;
    EventBus eventBus_;


    bool running_;

    // Per-invocation result store (TASK 3.1 §9.4): request_id ->
    // ExecutionResult for the current Run. Aggregate RuntimeResult
    // counters remain aggregate-only and are never used as
    // per-invocation evidence.
    std::unordered_map<std::string, ak::ExecutionResult>
        invocationResults_;

    // CAP0006-002: deterministic fault-injection seam used by the
    // Runtime test suite to verify the public exception boundary
    // (AK0035 §7.9 / §17.5). Test-only; never armed in
    // production execution. Private, therefore not part of the
    // Runtime Public API.
    friend struct RuntimeTestAccess;
    bool injectFailureForTesting_ = false;
};

}  // namespace ak::runtime
