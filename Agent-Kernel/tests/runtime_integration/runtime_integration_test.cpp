// ============================================================
// runtime_integration_test.cpp - TASK 3.1 §20 / TASK 3.2
// ============================================================
// Proof of the closed bounded Agent -> Runtime -> Agent cycle:
//
//   ModelResult -> ModelAction -> RuntimeInvocationRequest ->
//   RuntimePublicApiAdapter -> Runtime -> real capability ->
//   ExecutionResult -> RuntimeObservation -> Context
//
// Covers: contract values (T3.2-AC-001..004), registration
// (AC-006), payload transport (AC-007), real invocation
// (AC-008), per-invocation result retrieval (AC-009), failure
// mapping (AC-010), observation (AC-004/010), observation ->
// Context (AC-011), ModelResult -> ModelAction interpretation
// (AC-012), and the bounded deterministic E2E cycle (AC-022).
//
// The Agent interacts exclusively through
// ak::agent::RuntimeInteractionPort; Scheduler / Executor /
// CapabilityResolver / EventBus / Runtime internals never cross
// the Agent boundary (TASK 2 §8.3; T3.2-AC-016).
// ============================================================

#include <gtest/gtest.h>

#include <any>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

// Agent-owned contract surface (Agent boundary; no Runtime type).
#include <agent_kernel/agent/runtime/runtime_interaction_port.hpp>
#include <agent_kernel/agent/runtime/runtime_invocation_request.hpp>
#include <agent_kernel/agent/runtime/runtime_observation.hpp>
#include <agent_kernel/agent/runtime/runtime_submission_result.hpp>

// Integration adapter (the only Agent -> Runtime path).
#include <agent_kernel/runtime_integration/runtime_public_api_adapter.hpp>

// Runtime Public API (test-only direct use: registration and
// per-invocation result retrieval evidence).
#include <runtime.h>

// Context (observation -> context update; AK0043 / P1-IS004).
#include <agent_kernel/context/context.hpp>
#include <agent_kernel/context/context_agent_contract.hpp>
#include <agent_kernel/context/context_identity.hpp>
#include <agent_kernel/context/context_objects.hpp>

// Model + interpretation (AK0046 / P1-IS008; TASK 2 §12).
#include <agent_kernel/model/model.hpp>
#include <agent_kernel/model/model_identity.hpp>
#include <agent_kernel/model/model_input.hpp>
#include <agent_kernel/model/model_result.hpp>
#include <agent_kernel/model/model_state.hpp>
#include <agent_kernel/fwa/model_action.hpp>
#include <agent_kernel/tool/tool_identity.hpp>

namespace ak::runtime_integration {
namespace {

// ============================================================
// Deterministic capability invokers (real executable logic)
// ============================================================
std::string EchoInvoker(const std::string& payload) {
    return "echo:" + payload;
}

std::string TransformInvoker(const std::string& payload) {
    return "transform:" + payload;
}

std::string ThrowingInvoker(const std::string& /*payload*/) {
    throw std::runtime_error(
        "deterministic invoker failure (C1 failure-path fixture)");
}

// ============================================================
// Deterministic model double (P1-IS008 test-double pattern):
// returns scripted ModelResult payloads in order, then repeats
// the final output. ModelResult is Model-owned; the Agent
// interprets it (TASK 2 §12.1).
// ============================================================
class DeterministicModel final : public ak::model::Model {
public:
    explicit DeterministicModel(std::vector<std::string> outputs)
        : outputs_(std::move(outputs)) {
        if (outputs_.empty()) {
            outputs_.push_back("complete");
        }
    }

    ak::model::ModelId Id() const noexcept override {
        return ak::model::ModelId("runtime-integration-test-model");
    }

    ak::model::ModelLifecycleState State() const noexcept override {
        return ak::model::ModelLifecycleState::kReady;
    }

    ak::TransitionResult Initialize() override {
        return {ak::TransitionStatus::kAccepted, "ready"};
    }

    ak::TransitionResult Shutdown() override {
        return {ak::TransitionStatus::kAccepted, "shutdown"};
    }

    ak::model::ModelResult Infer(
        const ak::model::ModelInput& /*input*/) override {
        const std::string output =
            (output_index_ < outputs_.size())
                ? outputs_[output_index_++]
                : outputs_.back();
        return ak::model::ModelResult::Success(output);
    }

private:
    std::vector<std::string> outputs_;
    std::size_t output_index_ = 0;
};
// ============================================================
// Agent-owned ModelResult -> ModelAction interpretation
// (TASK 2 §12; non-normative reference vocabulary §12.3):
//   "tool:<capability_id>:<arguments>" -> kToolInvoke
//   "complete"                         -> kComplete
//   all other payloads                 -> kInvalid
// ============================================================
ak::agent::ModelAction InterpretModelResult(
    const ak::model::ModelResult& result) {
    if (!result.IsSuccess() || !result.Payload().has_value()) {
        return ak::agent::ModelAction::Invalid(
            result.IsFailure() ? result.Diagnostic()
                               : "invalid-model-result");
    }
    const std::string& payload = result.Payload().value();
    if (payload == "complete") {
        return ak::agent::ModelAction::Complete();
    }

    constexpr std::string_view kToolPrefix = "tool:";
    if (payload.rfind(kToolPrefix, 0) != 0) {
        return ak::agent::ModelAction::Invalid("unsupported-model-output");
    }

    const std::size_t capabilityBegin = kToolPrefix.size();
    const std::size_t capabilityEnd = payload.find(':', capabilityBegin);
    if (capabilityEnd == std::string::npos) {
        return ak::agent::ModelAction::Invalid("malformed-tool-output");
    }
    const std::string capability =
        payload.substr(capabilityBegin, capabilityEnd - capabilityBegin);
    const std::string arguments = payload.substr(capabilityEnd + 1);
    if (capability.empty() || arguments.empty()) {
        return ak::agent::ModelAction::Invalid("malformed-tool-output");
    }
    try {
        return ak::agent::ModelAction::InvokeTool(
            ak::tool::CapabilityId(capability), arguments);
    } catch (const std::invalid_argument&) {
        return ak::agent::ModelAction::Invalid("invalid-capability-identity");
    }
}

// ============================================================
// Context helpers (Agent applies observations through the
// existing Context public API; AK0043 / P1-IS004).
// ============================================================
void InitializeContextObject(ak::context::Context& context) {
    ak::context::ContextAgentContract& contract = context.AgentContract();
    const ak::context::ContextObjectId object_id =
        ak::context::MakeContextObjectId(1);
    EXPECT_TRUE(contract.Creation()
                    .CreateObject(object_id, "working_state", "initial",
                                  ak::context::ContextMetadata{})
                    .IsSuccess());
    EXPECT_TRUE(contract.Creation().InitializeObject(object_id).IsSuccess());
    EXPECT_TRUE(contract.Creation().ActivateObject(object_id).IsSuccess());
}

bool ApplyObservationToContext(
    ak::context::Context& context,
    const ak::agent::RuntimeObservation& observation) {
    ak::context::ContextAgentContract& contract = context.AgentContract();
    const ak::context::ContextObjectId object_id =
        ak::context::MakeContextObjectId(1);
    ak::context::ContextUpdateService& update = contract.Update();
    if (!update.BeginUpdate(object_id).IsSuccess()) {
        return false;
    }
    const std::string content =
        (observation.status == ak::agent::ObservationStatus::kSuccess)
            ? observation.output
            : observation.failure;
    if (!update.ApplyUpdate(object_id, content,
                            ak::context::ContextMetadata{})
             .IsSuccess()) {
        return false;
    }
    return update.CompleteUpdate(object_id).IsSuccess();
}

// ============================================================
// Bounded deterministic cycle driver (TASK 2 §20; TASK 3.1 §11)
// ============================================================
struct CycleRunResult {
    bool completed = false;
    std::size_t cycles_used = 0;
    std::vector<std::string> context_contents;
};

CycleRunResult RunBoundedCycle(DeterministicModel& model,
                               ak::context::Context& context,
                               std::size_t max_cycles) {
    CycleRunResult outcome;
    ak::context::ContextAgentContract& contract = context.AgentContract();
    const ak::context::ContextObjectId object_id =
        ak::context::MakeContextObjectId(1);

    for (std::size_t cycle = 0; cycle < max_cycles; ++cycle) {
        // 1-4. Model inference + Agent interpretation.
        const ak::model::ModelResult model_result =
            model.Infer(ak::model::ModelInput("agent-facing input"));
        const ak::agent::ModelAction action =
            InterpretModelResult(model_result);

        // Terminal conditions (TASK 2 §20.2 / §20.3).
        if (action.IsComplete()) {
            outcome.completed = true;
            outcome.cycles_used = cycle + 1;
            return outcome;
        }
        if (action.IsInvalid()) {
            outcome.cycles_used = cycle + 1;
            return outcome;
        }

        // 5-8. kToolInvoke -> RuntimeInvocationRequest -> port.
        const std::string request_id =
            "cycle-" + std::to_string(cycle + 1);
        const std::string capability_id = action.Capability()->Value();
        const std::string arguments = action.Arguments();

        // A fresh Runtime per bounded invocation (Runtime Run is
        // one-shot by its frozen state machine; TASK 2 §20).
        ak::runtime::Runtime runtime;
        RuntimePublicApiAdapter adapter(runtime);
        adapter.RegisterCapability(capability_id, "local", EchoInvoker);

        // The Agent sees only the Agent-owned port.
        ak::agent::RuntimeInteractionPort& port = adapter;
        const ak::agent::RuntimeSubmissionResult submission = port.Submit(
            ak::agent::RuntimeInvocationRequest{
                ak::agent::RuntimeRequestId(request_id),
                capability_id, arguments});
        if (!submission.accepted ||
            submission.status != ak::agent::SubmissionStatus::kCompleted) {
            outcome.cycles_used = cycle + 1;
            return outcome;
        }

        const ak::agent::RuntimeObservation observation =
            port.Observe(ak::agent::RuntimeRequestId(request_id));
        if (observation.status != ak::agent::ObservationStatus::kSuccess) {
            outcome.cycles_used = cycle + 1;
            return outcome;
        }

        // 14-15. Agent applies the observation to Context.
        if (!ApplyObservationToContext(context, observation)) {
            outcome.cycles_used = cycle + 1;
            return outcome;
        }
        const auto view = contract.Access().InspectObject(object_id);
        if (!view.IsSuccess()) {
            outcome.cycles_used = cycle + 1;
            return outcome;
        }
        outcome.context_contents.push_back(view.value.content);
        runtime.Stop();
    }
    outcome.cycles_used = max_cycles;
    return outcome;
}
// ============================================================
// Contract value tests (T3.2-AC-001..004)
// ============================================================
TEST(RuntimeContractTest, InvocationRequestCarriesCanonicalIdentity) {
    const ak::agent::RuntimeInvocationRequest request{
        ak::agent::RuntimeRequestId("req-xyz"), "demo.echo", "payload"};
    EXPECT_EQ(request.request_id.Value(), "req-xyz");
    EXPECT_EQ(request.capability_id, "demo.echo");
    EXPECT_EQ(request.payload, "payload");

    // request_id is a standalone Agent-owned string value with
    // non-empty validation (TASK 2 §9.2; F-003 CLOSED) - it is
    // not a Session/Workflow/Task/Event/Scheduler/Executor ID.
    EXPECT_THROW(ak::agent::RuntimeRequestId("   "), std::invalid_argument);
    EXPECT_THROW(ak::agent::RuntimeRequestId(""), std::invalid_argument);
}

TEST(RuntimeContractTest, SubmissionResultHasTerminalSemantics) {
    const ak::agent::RuntimeSubmissionResult completed{
        ak::agent::RuntimeRequestId("r1"), true,
        ak::agent::SubmissionStatus::kCompleted, ""};
    EXPECT_TRUE(completed.accepted);
    EXPECT_EQ(completed.status, ak::agent::SubmissionStatus::kCompleted);

    const ak::agent::RuntimeSubmissionResult rejected{
        ak::agent::RuntimeRequestId("r2"), false,
        ak::agent::SubmissionStatus::kRejected, "reason"};
    EXPECT_FALSE(rejected.accepted);
    EXPECT_EQ(rejected.status, ak::agent::SubmissionStatus::kRejected);
    EXPECT_FALSE(rejected.failure.empty());

    const ak::agent::RuntimeSubmissionResult failed{
        ak::agent::RuntimeRequestId("r3"), true,
        ak::agent::SubmissionStatus::kFailed, "reason"};
    EXPECT_TRUE(failed.accepted);
    EXPECT_EQ(failed.status, ak::agent::SubmissionStatus::kFailed);
    EXPECT_FALSE(failed.failure.empty());
}

TEST(RuntimeContractTest, ObservationCarriesPerInvocationOutcome) {
    const ak::agent::RuntimeObservation success{
        ak::agent::RuntimeRequestId("r1"), "demo.echo",
        ak::agent::ObservationStatus::kSuccess, "output", ""};
    EXPECT_EQ(success.status, ak::agent::ObservationStatus::kSuccess);
    EXPECT_EQ(success.output, "output");
    EXPECT_TRUE(success.failure.empty());

    const ak::agent::RuntimeObservation failure{
        ak::agent::RuntimeRequestId("r2"), "",
        ak::agent::ObservationStatus::kFailure, "", "reason"};
    EXPECT_EQ(failure.status, ak::agent::ObservationStatus::kFailure);
    EXPECT_TRUE(failure.output.empty());
    EXPECT_EQ(failure.failure, "reason");
}

TEST(RuntimeContractTest, PortIsAgentOwnedAndAdapterImplementsIt) {
    static_assert(
        std::is_base_of_v<ak::agent::RuntimeInteractionPort,
                          RuntimePublicApiAdapter>);
    EXPECT_EQ(ak::agent::RuntimeInteractionPort::RuntimePublicApiBoundary(),
              "Runtime Public API");
    EXPECT_TRUE(ak::agent::RuntimeInteractionPort::IsContractOnly());
    EXPECT_EQ(ak::agent::RuntimeInteractionPort::ContractVersion(), 1u);
}

TEST(RuntimeContractTest, BasePortDefaultsAreContractLevelSafe) {
    // B1: the base port performs no Runtime interaction; defaults
    // are contract-level rejected / not-observable.
    ak::agent::RuntimeInteractionPort port;
    const ak::agent::RuntimeSubmissionResult submission = port.Submit(
        ak::agent::RuntimeInvocationRequest{
            ak::agent::RuntimeRequestId("req-x"), "demo.echo", "p"});
    EXPECT_FALSE(submission.accepted);
    EXPECT_EQ(submission.status, ak::agent::SubmissionStatus::kRejected);

    const ak::agent::RuntimeObservation observation =
        port.Observe(ak::agent::RuntimeRequestId("req-x"));
    EXPECT_EQ(observation.status, ak::agent::ObservationStatus::kFailure);
}

// ============================================================
// Registration (T3.2-AC-006)
// ============================================================
TEST(RuntimeRegistrationTest, CapabilityRegistersThroughPublicPath) {
    ak::runtime::Runtime runtime;
    EXPECT_FALSE(runtime.HasCapability("demo.echo"));

    runtime.RegisterCapability("demo.echo", "local", EchoInvoker);
    EXPECT_TRUE(runtime.HasCapability("demo.echo"));

    // Duplicate registration overwrites deterministically
    // (TASK 3.1 §9.1; TASK 3.1 §13 API table).
    runtime.RegisterCapability("demo.echo", "local", TransformInvoker);
    EXPECT_TRUE(runtime.HasCapability("demo.echo"));
    EXPECT_FALSE(runtime.HasCapability("not.registered"));
}

// ============================================================
// Payload transport (T3.2-AC-007)
// ============================================================
TEST(RuntimeAdapterPayloadTest, PayloadReachesActualCapabilityInvocation) {
    ak::runtime::Runtime runtime;
    RuntimePublicApiAdapter adapter(runtime);
    adapter.RegisterCapability("demo.echo", "local", EchoInvoker);

    const ak::agent::RuntimeSubmissionResult submission = adapter.Submit(
        ak::agent::RuntimeInvocationRequest{
            ak::agent::RuntimeRequestId("payload-req-1"),
            "demo.echo", "hello-payload"});
    ASSERT_TRUE(submission.accepted);
    EXPECT_EQ(submission.status, ak::agent::SubmissionStatus::kCompleted);

    const ak::agent::RuntimeObservation observation =
        adapter.Observe(ak::agent::RuntimeRequestId("payload-req-1"));
    ASSERT_EQ(observation.status, ak::agent::ObservationStatus::kSuccess);
    // The invoker observed the exact payload supplied by the Agent
    // (TASK 2 §15: payload at invocation boundary == payload
    // supplied by the Agent, no silent loss).
    EXPECT_EQ(observation.output, "echo:hello-payload");
    EXPECT_EQ(observation.capability_id, "demo.echo");
    runtime.Stop();
}

// ============================================================
// Real capability invocation (T3.2-AC-008)
// ============================================================
TEST(RuntimeAdapterInvocationTest, RealCapabilityInvokerExecutesNotSynthetic) {
    ak::runtime::Runtime runtime;
    RuntimePublicApiAdapter adapter(runtime);
    adapter.RegisterCapability("demo.echo", "local", EchoInvoker);

    const ak::agent::RuntimeSubmissionResult submission = adapter.Submit(
        ak::agent::RuntimeInvocationRequest{
            ak::agent::RuntimeRequestId("real-req-1"),
            "demo.echo", "real-output"});
    ASSERT_TRUE(submission.accepted);
    EXPECT_EQ(submission.status, ak::agent::SubmissionStatus::kCompleted);

    const ak::agent::RuntimeObservation observation =
        adapter.Observe(ak::agent::RuntimeRequestId("real-req-1"));
    ASSERT_EQ(observation.status, ak::agent::ObservationStatus::kSuccess);
    // The output is the registered invoker's REAL output - never
    // a synthetic "<name>:<version> completed" marker.
    EXPECT_EQ(observation.output, "echo:real-output");
    EXPECT_NE(observation.output, "demo.echo:1 completed");
    runtime.Stop();
}

TEST(RuntimeAdapterInvocationTest, AdapterOverridesPortDefaults) {
    ak::runtime::Runtime runtime;
    RuntimePublicApiAdapter adapter(runtime);
    adapter.RegisterCapability("demo.echo", "local", EchoInvoker);

    ak::agent::RuntimeInteractionPort& port = adapter;
    const ak::agent::RuntimeSubmissionResult submission = port.Submit(
        ak::agent::RuntimeInvocationRequest{
            ak::agent::RuntimeRequestId("override-req"),
            "demo.echo", "p"});
    EXPECT_TRUE(submission.accepted);
    EXPECT_EQ(submission.status, ak::agent::SubmissionStatus::kCompleted);
    runtime.Stop();
}
// ============================================================
// Per-invocation result retrieval (T3.2-AC-009)
// ============================================================
TEST(RuntimeAdapterResultTest, PerInvocationResultsAreDistinctByRequestId) {
    // Invocation A.
    ak::runtime::Runtime runtime_a;
    RuntimePublicApiAdapter adapter_a(runtime_a);
    adapter_a.RegisterCapability("demo.echo", "local", EchoInvoker);
    const ak::agent::RuntimeSubmissionResult submission_a = adapter_a.Submit(
        ak::agent::RuntimeInvocationRequest{
            ak::agent::RuntimeRequestId("req-A"), "demo.echo",
            "payload-A"});
    ASSERT_EQ(submission_a.status, ak::agent::SubmissionStatus::kCompleted);

    // Invocation B.
    ak::runtime::Runtime runtime_b;
    RuntimePublicApiAdapter adapter_b(runtime_b);
    adapter_b.RegisterCapability("demo.echo", "local", EchoInvoker);
    const ak::agent::RuntimeSubmissionResult submission_b = adapter_b.Submit(
        ak::agent::RuntimeInvocationRequest{
            ak::agent::RuntimeRequestId("req-B"), "demo.echo",
            "payload-B"});
    ASSERT_EQ(submission_b.status, ak::agent::SubmissionStatus::kCompleted);

    // request_id -> specific invocation -> specific result.
    const std::optional<ak::ExecutionResult> result_a =
        runtime_a.GetInvocationResult("req-A");
    const std::optional<ak::ExecutionResult> result_b =
        runtime_b.GetInvocationResult("req-B");
    ASSERT_TRUE(result_a.has_value());
    ASSERT_TRUE(result_b.has_value());
    EXPECT_TRUE(result_a->IsSuccess());
    EXPECT_TRUE(result_b->IsSuccess());

    const std::string output_a =
        std::any_cast<std::string>(result_a->output.value());
    const std::string output_b =
        std::any_cast<std::string>(result_b->output.value());
    EXPECT_EQ(output_a, "echo:payload-A");
    EXPECT_EQ(output_b, "echo:payload-B");
    EXPECT_NE(output_a, output_b);

    // No cross-talk: each Runtime answers only its own request_id.
    EXPECT_FALSE(runtime_a.GetInvocationResult("req-B").has_value());
    EXPECT_FALSE(runtime_b.GetInvocationResult("req-A").has_value());
    runtime_a.Stop();
    runtime_b.Stop();
}

TEST(RuntimeAdapterResultTest, InvocationResultPreservesRequestId) {
    ak::runtime::Runtime runtime;
    RuntimePublicApiAdapter adapter(runtime);
    adapter.RegisterCapability("demo.echo", "local", EchoInvoker);
    const ak::agent::RuntimeSubmissionResult submission = adapter.Submit(
        ak::agent::RuntimeInvocationRequest{
            ak::agent::RuntimeRequestId("req-keep"), "demo.echo", "p"});
    ASSERT_EQ(submission.status, ak::agent::SubmissionStatus::kCompleted);

    const std::optional<ak::ExecutionResult> result =
        runtime.GetInvocationResult("req-keep");
    ASSERT_TRUE(result.has_value());
    ASSERT_TRUE(result->request_id.has_value());
    EXPECT_EQ(result->request_id.value(), "req-keep");
    runtime.Stop();
}

// ============================================================
// Failure mapping (T3.2-AC-010)
// ============================================================
TEST(RuntimeAdapterFailureTest, InvalidInvocationIsRejectedBeforeRuntime) {
    ak::runtime::Runtime runtime;
    RuntimePublicApiAdapter adapter(runtime);

    // Empty capability_id -> rejected.
    const ak::agent::RuntimeSubmissionResult sub1 = adapter.Submit(
        ak::agent::RuntimeInvocationRequest{
            ak::agent::RuntimeRequestId("rej-1"), "", "payload"});
    EXPECT_FALSE(sub1.accepted);
    EXPECT_EQ(sub1.status, ak::agent::SubmissionStatus::kRejected);
    EXPECT_NE(sub1.failure.find("invalid-invocation"), std::string::npos);

    // Blank payload -> rejected.
    const ak::agent::RuntimeSubmissionResult sub2 = adapter.Submit(
        ak::agent::RuntimeInvocationRequest{
            ak::agent::RuntimeRequestId("rej-2"), "demo.echo", "   "});
    EXPECT_FALSE(sub2.accepted);
    EXPECT_EQ(sub2.status, ak::agent::SubmissionStatus::kRejected);

    // The rejection is deterministically observable.
    const ak::agent::RuntimeObservation obs =
        adapter.Observe(ak::agent::RuntimeRequestId("rej-1"));
    EXPECT_EQ(obs.status, ak::agent::ObservationStatus::kFailure);
    EXPECT_NE(obs.failure.find("invalid-invocation"), std::string::npos);
}

TEST(RuntimeAdapterFailureTest, UnregisteredCapabilityYieldsCapabilityNotFound) {
    ak::runtime::Runtime runtime;
    RuntimePublicApiAdapter adapter(runtime);
    // Intentionally no capability registered.

    const ak::agent::RuntimeSubmissionResult submission = adapter.Submit(
        ak::agent::RuntimeInvocationRequest{
            ak::agent::RuntimeRequestId("missing-req-1"),
            "not.registered", "x"});
    EXPECT_TRUE(submission.accepted);
    EXPECT_EQ(submission.status, ak::agent::SubmissionStatus::kFailed);
    EXPECT_NE(submission.failure.find("capability-not-found:not.registered"),
              std::string::npos);

    const ak::agent::RuntimeObservation observation =
        adapter.Observe(ak::agent::RuntimeRequestId("missing-req-1"));
    EXPECT_EQ(observation.status, ak::agent::ObservationStatus::kFailure);
    EXPECT_NE(observation.failure.find("capability-not-found:not.registered"),
              std::string::npos);
}

TEST(RuntimeAdapterFailureTest, InvokerFailureYieldsFailureObservation) {
    ak::runtime::Runtime runtime;
    RuntimePublicApiAdapter adapter(runtime);
    adapter.RegisterCapability("explode.cap", "local", ThrowingInvoker);

    const ak::agent::RuntimeSubmissionResult submission = adapter.Submit(
        ak::agent::RuntimeInvocationRequest{
            ak::agent::RuntimeRequestId("fail-req-1"),
            "explode.cap", "boom"});
    ASSERT_TRUE(submission.accepted);
    EXPECT_EQ(submission.status, ak::agent::SubmissionStatus::kFailed);

    const ak::agent::RuntimeObservation observation =
        adapter.Observe(ak::agent::RuntimeRequestId("fail-req-1"));
    EXPECT_EQ(observation.status, ak::agent::ObservationStatus::kFailure);
    EXPECT_NE(observation.failure.find("capability-invocation-failed:explode.cap"),
              std::string::npos);
}

TEST(RuntimeAdapterFailureTest, UnknownRequestIdYieldsResultNotFound) {
    ak::runtime::Runtime runtime;
    RuntimePublicApiAdapter adapter(runtime);
    const ak::agent::RuntimeObservation observation =
        adapter.Observe(ak::agent::RuntimeRequestId("never-submitted"));
    EXPECT_EQ(observation.status, ak::agent::ObservationStatus::kFailure);
    EXPECT_NE(observation.failure.find("result-not-found:never-submitted"),
              std::string::npos);
}
// ============================================================
// Observation -> Context (T3.2-AC-011)
// ============================================================
TEST(RuntimeContextTest, SuccessObservationUpdatesAgentContext) {
    ak::context::Context context(ak::context::MakeContextIdentity(21));
    InitializeContextObject(context);

    ak::runtime::Runtime runtime;
    RuntimePublicApiAdapter adapter(runtime);
    adapter.RegisterCapability("demo.echo", "local", EchoInvoker);
    const ak::agent::RuntimeSubmissionResult submission = adapter.Submit(
        ak::agent::RuntimeInvocationRequest{
            ak::agent::RuntimeRequestId("ctx-req-1"),
            "demo.echo", "context-content"});
    ASSERT_EQ(submission.status, ak::agent::SubmissionStatus::kCompleted);
    const ak::agent::RuntimeObservation observation =
        adapter.Observe(ak::agent::RuntimeRequestId("ctx-req-1"));
    ASSERT_EQ(observation.status, ak::agent::ObservationStatus::kSuccess);

    // Agent applies the observation through the existing Context
    // Update API (Begin/Apply/Complete; AK0043/P1-IS004).
    EXPECT_TRUE(ApplyObservationToContext(context, observation));

    const auto view = context.AgentContract().Access().InspectObject(
        ak::context::MakeContextObjectId(1));
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_EQ(view.value.content, "echo:context-content");
    runtime.Stop();
}

TEST(RuntimeContextTest, FailureObservationIsRecordedInContext) {
    ak::context::Context context(ak::context::MakeContextIdentity(22));
    InitializeContextObject(context);

    ak::runtime::Runtime runtime;
    RuntimePublicApiAdapter adapter(runtime);
    const ak::agent::RuntimeSubmissionResult submission = adapter.Submit(
        ak::agent::RuntimeInvocationRequest{
            ak::agent::RuntimeRequestId("ctx-fail-1"),
            "not.registered", "x"});
    EXPECT_EQ(submission.status, ak::agent::SubmissionStatus::kFailed);
    const ak::agent::RuntimeObservation observation =
        adapter.Observe(ak::agent::RuntimeRequestId("ctx-fail-1"));
    ASSERT_EQ(observation.status, ak::agent::ObservationStatus::kFailure);

    EXPECT_TRUE(ApplyObservationToContext(context, observation));

    const auto view = context.AgentContract().Access().InspectObject(
        ak::context::MakeContextObjectId(1));
    ASSERT_TRUE(view.IsSuccess());
    EXPECT_NE(view.value.content.find("capability-not-found:not.registered"),
              std::string::npos);
    runtime.Stop();
}

// ============================================================
// ModelResult -> ModelAction interpretation (T3.2-AC-012)
// ============================================================
TEST(ModelInterpretationTest, ToolIntentYieldsToolInvoke) {
    const ak::agent::ModelAction action = InterpretModelResult(
        ak::model::ModelResult::Success("tool:demo.echo:hello"));
    EXPECT_TRUE(action.IsToolInvoke());
    ASSERT_NE(action.Capability(), nullptr);
    EXPECT_EQ(action.Capability()->Value(), "demo.echo");
    EXPECT_EQ(action.Arguments(), "hello");
}

TEST(ModelInterpretationTest, CompletionYieldsComplete) {
    const ak::agent::ModelAction action = InterpretModelResult(
        ak::model::ModelResult::Success("complete"));
    EXPECT_TRUE(action.IsComplete());
    EXPECT_FALSE(action.IsToolInvoke());
}

TEST(ModelInterpretationTest, UnsupportedOutputYieldsInvalid) {
    const ak::agent::ModelAction action = InterpretModelResult(
        ak::model::ModelResult::Success("unexpected output"));
    EXPECT_TRUE(action.IsInvalid());
    EXPECT_FALSE(action.Reason().empty());
}

TEST(ModelInterpretationTest, MalformedToolOutputYieldsInvalid) {
    const ak::agent::ModelAction action = InterpretModelResult(
        ak::model::ModelResult::Success("tool:no-arguments"));
    EXPECT_TRUE(action.IsInvalid());
}

TEST(ModelInterpretationTest, ModelFailureYieldsInvalid) {
    const ak::agent::ModelAction action = InterpretModelResult(
        ak::model::ModelResult::Failure("provider transport error"));
    EXPECT_TRUE(action.IsInvalid());
    EXPECT_NE(action.Reason().find("provider transport error"),
              std::string::npos);
}

TEST(ModelInterpretationTest, ModelActionIsADecisionNotExecution) {
    // ModelAction is an Agent-owned decision value; it references
    // no Runtime type and performs no Runtime action (TASK 2
    // §12.4). Execution is the Agent's decision via the port.
    const ak::agent::ModelAction action =
        ak::agent::ModelAction::InvokeTool(
            ak::tool::CapabilityId("demo.echo"), "args");
    EXPECT_TRUE(action.IsToolInvoke());
    EXPECT_EQ(action.Capability()->Value(), "demo.echo");
    EXPECT_EQ(action.Arguments(), "args");
}
// ============================================================
// End-to-end bounded cycle (T3.2-AC-022)
// ============================================================
TEST(RuntimeIntegrationE2ETest, BoundedCycleCompletesDeterministically) {
    // Model double: first a tool intent, then completion.
    DeterministicModel model({"tool:demo.echo:hello-world", "complete"});
    ak::context::Context context(ak::context::MakeContextIdentity(7));
    InitializeContextObject(context);

    const CycleRunResult outcome = RunBoundedCycle(model, context, 8);

    EXPECT_TRUE(outcome.completed);
    EXPECT_EQ(outcome.cycles_used, 2u);
    ASSERT_EQ(outcome.context_contents.size(), 1u);
    EXPECT_EQ(outcome.context_contents[0], "echo:hello-world");
}

TEST(RuntimeIntegrationE2ETest, BoundedCycleIsDeterministic) {
    DeterministicModel first({"tool:demo.echo:alpha", "complete"});
    DeterministicModel second({"tool:demo.echo:alpha", "complete"});
    ak::context::Context context_a(ak::context::MakeContextIdentity(31));
    ak::context::Context context_b(ak::context::MakeContextIdentity(32));
    InitializeContextObject(context_a);
    InitializeContextObject(context_b);

    const CycleRunResult run_a = RunBoundedCycle(first, context_a, 8);
    const CycleRunResult run_b = RunBoundedCycle(second, context_b, 8);

    EXPECT_TRUE(run_a.completed);
    EXPECT_TRUE(run_b.completed);
    EXPECT_EQ(run_a.cycles_used, run_b.cycles_used);
    EXPECT_EQ(run_a.context_contents, run_b.context_contents);
}

TEST(RuntimeIntegrationE2ETest, CompletionTerminatesWithoutRuntimeInvocation) {
    // TASK 2 §20.2: kComplete requires no Runtime invocation.
    DeterministicModel model({"complete"});
    ak::context::Context context(ak::context::MakeContextIdentity(33));
    InitializeContextObject(context);

    const CycleRunResult outcome = RunBoundedCycle(model, context, 8);

    EXPECT_TRUE(outcome.completed);
    EXPECT_EQ(outcome.cycles_used, 1u);
    EXPECT_TRUE(outcome.context_contents.empty());
}

TEST(RuntimeIntegrationE2ETest, InvalidOutputTerminatesBoundedCycle) {
    // TASK 2 §20.3: kInvalid terminates the bounded cycle.
    DeterministicModel model({"not-a-valid-output"});
    ak::context::Context context(ak::context::MakeContextIdentity(34));
    InitializeContextObject(context);

    const CycleRunResult outcome = RunBoundedCycle(model, context, 8);

    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.cycles_used, 1u);
    EXPECT_TRUE(outcome.context_contents.empty());
}

TEST(RuntimeIntegrationE2ETest, CycleRespectsMaxCyclesBound) {
    // A model that never completes: the loop must terminate at the
    // deterministic bound (TASK 2 §20.4; TASK 3.1 §11).
    DeterministicModel model({"tool:demo.echo:loop"});
    ak::context::Context context(ak::context::MakeContextIdentity(35));
    InitializeContextObject(context);

    const CycleRunResult outcome = RunBoundedCycle(model, context, 3);

    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.cycles_used, 3u);
}

}  // namespace
}  // namespace ak::runtime_integration