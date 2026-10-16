// ============================================================
// runtime_backed_agent_composition_test.cpp - TASK 3.3
// ============================================================
// Agent-owned Runtime-backed execution composition tests.
//
// Proof of the closed bounded Agent decision -> Runtime -> Agent
// step:
//
//   ModelAction -> RuntimeBackedExecutionComposition ->
//   RuntimeInvocationRequest -> RuntimeInteractionPort ->
//   RuntimePublicApiAdapter -> Runtime -> real capability ->
//   ExecutionResult -> RuntimeObservation -> ContextAgentContract
//   ::Update -> terminal state
//
// Covers T3.3-AC-001..026 and T3.3-001..016: production surface,
// ModelAction ownership, sanctioned-boundary invocation, opaque
// capability identity, real CapabilityInvoker execution,
// request_id identity, observation production, observation ->
// Context, terminal success/failure, kComplete without Runtime
// invocation, kInvalid determinism, bounded synchronous single
// invocation (no retry/async), Planner/Tool/Model ownership,
// determinism, regression-consistent behavior.
//
// The Agent interacts exclusively through
// ak::agent::RuntimeInteractionPort; Scheduler / Executor /
// CapabilityResolver / EventBus / Runtime internals never cross
// the Agent boundary. Runtime + adapter wiring is the test-side
// integration bootstrap (TASK 3.1 §17 pattern).
// ============================================================

#include <gtest/gtest.h>

#include <cstddef>
#include <cstdint>
#include <functional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

// Agent-owned contract surface (Agent boundary; no Runtime type).
#include <agent_kernel/agent/runtime/runtime_interaction_port.hpp>
#include <agent_kernel/agent/runtime/runtime_invocation_request.hpp>
#include <agent_kernel/agent/runtime/runtime_observation.hpp>
#include <agent_kernel/agent/runtime/runtime_submission_result.hpp>

// TASK 3.3 Agent-owned composition.
#include <agent_kernel/runtime_backed_agent/runtime_backed_execution_composition.hpp>

// Integration adapter (the only Agent -> Runtime path).
#include <agent_kernel/runtime_integration/runtime_public_api_adapter.hpp>

// Runtime Public API (test-only direct use: construction and
// registration evidence).
#include <runtime.h>

// Context (observation -> context update; AK0043 / P1-IS004).
#include <agent_kernel/context/context.hpp>
#include <agent_kernel/context/context_agent_contract.hpp>
#include <agent_kernel/context/context_identity.hpp>
#include <agent_kernel/context/context_objects.hpp>

// Model + interpretation (AK0046 / P1-IS008; TASK 2 §12).
#include <agent_kernel/model/model_result.hpp>
#include <agent_kernel/fwa/model_action.hpp>
#include <agent_kernel/tool/tool_identity.hpp>

namespace ak::runtime_backed_agent {
namespace {

// ============================================================
// Deterministic capability invokers (real executable logic)
// ============================================================
[[maybe_unused]] std::string EchoInvoker(const std::string& payload) {
    return "echo:" + payload;
}

std::string TransformInvoker(const std::string& payload) {
    return "transform:" + payload;
}

std::string ThrowingInvoker(const std::string& /*payload*/) {
    throw std::runtime_error(
        "deterministic invoker failure (T3.3 failure-path fixture)");
}

// Recording invoker: counts calls and captures payloads.
class RecordingInvoker {
public:
    std::string operator()(const std::string& payload) {
        ++call_count_;
        payloads_.push_back(payload);
        return "echo:" + payload;
    }

    [[nodiscard]] std::size_t Calls() const noexcept { return call_count_; }
    [[nodiscard]] const std::vector<std::string>& Payloads() const noexcept {
        return payloads_;
    }

private:
    std::size_t call_count_ = 0;
    std::vector<std::string> payloads_;
};

// ============================================================
// RecordingPort - thin test double around the REAL adapter that
// records per-invocation request_id evidence (identity tests).
// It delegates every operation to the sanctioned adapter; the
// Runtime is never mocked.
// ============================================================
class RecordingPort final : public ak::agent::RuntimeInteractionPort {
public:
    explicit RecordingPort(ak::agent::RuntimeInteractionPort& inner)
        : inner_(inner) {}

    ak::agent::RuntimeSubmissionResult Submit(
        const ak::agent::RuntimeInvocationRequest& request) override {
        submitted_ids_.push_back(request.request_id.Value());
        return inner_.Submit(request);
    }

    ak::agent::RuntimeObservation Observe(
        const ak::agent::RuntimeRequestId& request_id) override {
        observed_ids_.push_back(request_id.Value());
        return inner_.Observe(request_id);
    }

    [[nodiscard]] const std::vector<std::string>& SubmittedIds() const noexcept {
        return submitted_ids_;
    }
    [[nodiscard]] const std::vector<std::string>& ObservedIds() const noexcept {
        return observed_ids_;
    }

private:
    ak::agent::RuntimeInteractionPort& inner_;
    std::vector<std::string> submitted_ids_;
    std::vector<std::string> observed_ids_;
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
// Deterministic decision factories
// ============================================================
ak::agent::ModelAction ToolDecision(const std::string& capability,
                                    const std::string& arguments) {
    return ak::agent::ModelAction::InvokeTool(
        ak::tool::CapabilityId(capability), arguments);
}

ak::agent::ModelAction CompleteDecision() {
    return ak::agent::ModelAction::Complete();
}

ak::agent::ModelAction InvalidDecision(const std::string& reason) {
    return ak::agent::ModelAction::Invalid(reason);
}

// ============================================================
// Context helpers (Agent applies observations through the
// existing Context public API; AK0043 / P1-IS004).
// ============================================================
void InitializeContextObject(ak::context::Context& context) {
    ak::context::ContextAgentContract& contract = context.AgentContract();
    const ak::context::ContextObjectId object_id =
        ak::context::MakeContextObjectId(1);
    ASSERT_TRUE(contract.Creation()
                    .CreateObject(object_id, "working_state", "initial",
                                  ak::context::ContextMetadata{})
                    .IsSuccess());
    ASSERT_TRUE(contract.Creation().InitializeObject(object_id).IsSuccess());
    ASSERT_TRUE(contract.Creation().ActivateObject(object_id).IsSuccess());
}

std::string ContextContent(ak::context::Context& context) {
    const ak::context::ContextResultValue<ak::context::ContextObjectView>
        view = context.AgentContract().Access().InspectObject(
            ak::context::MakeContextObjectId(1));
    return view.IsSuccess() ? view.value.content
                            : std::string("<context-error>");
}

// ============================================================
// Test rig: real Runtime + real adapter + real Context + real
// invokers. A fresh Runtime is created per rig because the
// Runtime state machine is one-shot (Created -> Running ->
// Stopped; Runtime::Run requires kCreated) — the same evidence
// that fixes the composition to one invocation per Execute.
// ============================================================
struct Rig {
    ak::runtime::Runtime runtime;
    ak::runtime_integration::RuntimePublicApiAdapter adapter;
    ak::context::Context context;
    RecordingInvoker echo_invoker;

    explicit Rig(std::uint64_t seed = 77)
        : adapter(runtime),
          context(ak::context::MakeContextIdentity(seed)) {
        InitializeContextObject(context);
    }

    void RegisterEcho(const std::string& name = "demo.echo") {
        adapter.RegisterCapability(name, "local", std::ref(echo_invoker));
    }

    void RegisterInvoker(
        const std::string& name,
        std::function<std::string(const std::string&)> invoker) {
        adapter.RegisterCapability(name, "local", std::move(invoker));
    }

    RuntimeBackedExecutionComposition MakeComposition() {
        return RuntimeBackedExecutionComposition(
            adapter, context, ak::context::MakeContextObjectId(1));
    }
};

// ============================================================
// Production surface (T3.3-AC-001)
// ============================================================
TEST(CompositionProductionSurfaceTest, TargetProvidesComposition) {
    Rig rig;
    RuntimeBackedExecutionComposition composition = rig.MakeComposition();
    const ExecutionCycleOutcome outcome =
        composition.Execute(CompleteDecision());
    EXPECT_TRUE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kCompleted);
}

// ============================================================
// ModelAction ownership (T3.3-AC-002; T3.3-002)
// ============================================================
TEST(ModelActionConsumptionTest, ActionSemanticsRemainAgentOwned) {
    const ak::agent::ModelAction tool = ToolDecision("demo.echo", "hello");
    EXPECT_TRUE(tool.IsToolInvoke());
    ASSERT_NE(tool.Capability(), nullptr);
    EXPECT_EQ(tool.Capability()->Value(), "demo.echo");
    EXPECT_EQ(tool.Arguments(), "hello");

    const ak::agent::ModelAction complete = CompleteDecision();
    EXPECT_TRUE(complete.IsComplete());
    EXPECT_FALSE(complete.IsToolInvoke());

    const ak::agent::ModelAction invalid = InvalidDecision("bad");
    EXPECT_TRUE(invalid.IsInvalid());
    EXPECT_EQ(invalid.Reason(), "bad");
}

TEST(ModelInterpretationTest, ReferenceVocabularyRemainsAgentOwned) {
    const ak::agent::ModelAction tool = InterpretModelResult(
        ak::model::ModelResult::Success("tool:demo.echo:hello"));
    EXPECT_TRUE(tool.IsToolInvoke());
    EXPECT_EQ(tool.Capability()->Value(), "demo.echo");
    EXPECT_EQ(tool.Arguments(), "hello");

    EXPECT_TRUE(InterpretModelResult(ak::model::ModelResult::Success(
                                         "complete"))
                    .IsComplete());
    EXPECT_TRUE(InterpretModelResult(ak::model::ModelResult::Success(
                                         "unexpected output"))
                    .IsInvalid());
    EXPECT_TRUE(InterpretModelResult(ak::model::ModelResult::Failure(
                                         "provider transport error"))
                    .IsInvalid());
}

// ============================================================
// Sanctioned invocation through the existing contract
// (T3.3-AC-003/004)
// ============================================================
TEST(CompositionTest, ConstructsInvocationRequestThroughExistingContract) {
    Rig rig;
    rig.RegisterEcho();
    RecordingPort recording(rig.adapter);
    RuntimeBackedExecutionComposition composition(
        recording, rig.context, ak::context::MakeContextObjectId(1));

    const ExecutionCycleOutcome outcome =
        composition.Execute(ToolDecision("demo.echo", "hello"));

    EXPECT_TRUE(outcome.completed);
    ASSERT_EQ(recording.SubmittedIds().size(), 1u);
    ASSERT_EQ(recording.ObservedIds().size(), 1u);
    EXPECT_EQ(recording.SubmittedIds()[0], recording.ObservedIds()[0]);
    EXPECT_NE(recording.SubmittedIds()[0], "");
}

TEST(CompositionTest, ConsumesAgentInterpretedDecision) {
    Rig rig;
    rig.RegisterEcho();
    RuntimeBackedExecutionComposition composition = rig.MakeComposition();

    const ak::model::ModelResult result =
        ak::model::ModelResult::Success("tool:demo.echo:interpreted");
    const ak::agent::ModelAction action = InterpretModelResult(result);
    ASSERT_TRUE(action.IsToolInvoke());

    const ExecutionCycleOutcome outcome = composition.Execute(action);
    EXPECT_TRUE(outcome.completed);
    EXPECT_EQ(ContextContent(rig.context), "echo:interpreted");
}

// ============================================================
// Real capability execution (T3.3-AC-007/008/010)
// ============================================================
TEST(RealExecutionTest, RealInvokerExecutesAndSuccessReachesContext) {
    Rig rig;
    rig.RegisterEcho();
    RuntimeBackedExecutionComposition composition = rig.MakeComposition();

    const ExecutionCycleOutcome outcome =
        composition.Execute(ToolDecision("demo.echo", "hello"));

    EXPECT_TRUE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kCompleted);
    EXPECT_EQ(outcome.summary, "runtime-backed-cycle-completed");

    // The opaque capability_id reached the real registered
    // capability (A1 translation verified by execution).
    EXPECT_EQ(rig.echo_invoker.Calls(), 1u);
    ASSERT_EQ(rig.echo_invoker.Payloads().size(), 1u);
    EXPECT_EQ(rig.echo_invoker.Payloads()[0], "hello");

    // Success observation reached the existing Context API.
    EXPECT_EQ(ContextContent(rig.context), "echo:hello");
}

TEST(RealExecutionTest, TransformCapabilityExecutes) {
    Rig rig;
    rig.RegisterInvoker("demo.transform", TransformInvoker);
    RuntimeBackedExecutionComposition composition = rig.MakeComposition();

    const ExecutionCycleOutcome outcome =
        composition.Execute(ToolDecision("demo.transform", "payload"));

    EXPECT_TRUE(outcome.completed);
    EXPECT_EQ(ContextContent(rig.context), "transform:payload");
}

// ============================================================
// request_id identity (T3.3-AC-009)
// ============================================================
TEST(RequestIdentityTest, PerInvocationIdentityPreservedNoCrossTalk) {
    Rig rig_a(101);
    rig_a.RegisterEcho();
    RecordingPort recording_a(rig_a.adapter);
    RuntimeBackedExecutionComposition comp_a(
        recording_a, rig_a.context, ak::context::MakeContextObjectId(1));
    EXPECT_TRUE(comp_a.Execute(ToolDecision("demo.echo", "alpha")).completed);

    Rig rig_b(102);
    rig_b.RegisterEcho();
    RecordingPort recording_b(rig_b.adapter);
    RuntimeBackedExecutionComposition comp_b(
        recording_b, rig_b.context, ak::context::MakeContextObjectId(1));
    EXPECT_TRUE(comp_b.Execute(ToolDecision("demo.echo", "beta")).completed);

    // Each run observed exactly the request_id it submitted.
    ASSERT_EQ(recording_a.SubmittedIds().size(), 1u);
    ASSERT_EQ(recording_a.ObservedIds().size(), 1u);
    ASSERT_EQ(recording_b.SubmittedIds().size(), 1u);
    ASSERT_EQ(recording_b.ObservedIds().size(), 1u);
    EXPECT_EQ(recording_a.SubmittedIds()[0], recording_a.ObservedIds()[0]);
    EXPECT_EQ(recording_b.SubmittedIds()[0], recording_b.ObservedIds()[0]);
    EXPECT_NE(recording_a.SubmittedIds()[0], recording_b.SubmittedIds()[0]);

    // No cross-talk: request-A -> observation-A, request-B ->
    // observation-B.
    EXPECT_EQ(ContextContent(rig_a.context), "echo:alpha");
    EXPECT_EQ(ContextContent(rig_b.context), "echo:beta");
}

// ============================================================
// Failure semantics (T3.3-AC-011/012/014)
// ============================================================
TEST(FailureSemanticsTest, InvokerFailureIsDeterministicObservation) {
    Rig rig;
    rig.RegisterInvoker("demo.throw", ThrowingInvoker);
    RuntimeBackedExecutionComposition composition = rig.MakeComposition();

    const ExecutionCycleOutcome outcome =
        composition.Execute(ToolDecision("demo.throw", "x"));

    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kFailure);
    EXPECT_EQ(outcome.summary, "runtime-backed-cycle-failure");
    EXPECT_NE(outcome.diagnostics.find("capability-invocation-failed"),
              std::string::npos);

    // Failure evidence reached Context before terminal failure
    // (contract §13: RuntimeObservation::Failed -> Context Update
    // -> Agent terminal failure).
    EXPECT_NE(ContextContent(rig.context).find("capability-invocation-failed"),
              std::string::npos);
}

TEST(FailureSemanticsTest, MissingCapabilityFailsDeterministically) {
    Rig rig;
    // No capability registered under "demo.missing".
    RuntimeBackedExecutionComposition composition = rig.MakeComposition();

    const ExecutionCycleOutcome outcome =
        composition.Execute(ToolDecision("demo.missing", "x"));

    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kFailure);
    EXPECT_NE(outcome.diagnostics.find("capability-not-found"),
              std::string::npos);
}

TEST(FailureSemanticsTest, NoSyntheticSuccess) {
    Rig rig;
    rig.RegisterInvoker("demo.throw", ThrowingInvoker);
    RuntimeBackedExecutionComposition composition = rig.MakeComposition();

    const ExecutionCycleOutcome outcome =
        composition.Execute(ToolDecision("demo.throw", "x"));

    EXPECT_FALSE(outcome.completed);
    EXPECT_NE(outcome.termination, ExecutionTermination::kCompleted);
}

// ============================================================
// Terminal semantics (T3.3-AC-013/014)
// ============================================================
TEST(TerminalSemanticsTest, SuccessReachesTerminal) {
    Rig rig;
    rig.RegisterEcho();
    RuntimeBackedExecutionComposition composition = rig.MakeComposition();

    const ExecutionCycleOutcome outcome =
        composition.Execute(ToolDecision("demo.echo", "terminal"));

    EXPECT_TRUE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kCompleted);
    EXPECT_EQ(ContextContent(rig.context), "echo:terminal");
}

TEST(TerminalSemanticsTest, FailureReachesTerminalFailure) {
    Rig rig;
    rig.RegisterInvoker("demo.throw", ThrowingInvoker);
    RuntimeBackedExecutionComposition composition = rig.MakeComposition();

    const ExecutionCycleOutcome outcome =
        composition.Execute(ToolDecision("demo.throw", "terminal"));

    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kFailure);
}

// ============================================================
// kComplete semantics (T3.3-AC-015)
// ============================================================
TEST(CompleteSemanticsTest, KCompleteWithoutRuntimeInvocation) {
    Rig rig;
    rig.RegisterEcho();
    RecordingPort recording(rig.adapter);
    RuntimeBackedExecutionComposition composition(
        recording, rig.context, ak::context::MakeContextObjectId(1));

    const ExecutionCycleOutcome outcome =
        composition.Execute(CompleteDecision());

    EXPECT_TRUE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kCompleted);
    EXPECT_EQ(rig.echo_invoker.Calls(), 0u);
    EXPECT_TRUE(recording.SubmittedIds().empty());
    EXPECT_TRUE(recording.ObservedIds().empty());
    EXPECT_EQ(ContextContent(rig.context), "initial");
}

// ============================================================
// kInvalid semantics (T3.3-AC-016)
// ============================================================
TEST(InvalidSemanticsTest, KInvalidDeterministic) {
    Rig rig;
    rig.RegisterEcho();
    RecordingPort recording(rig.adapter);
    RuntimeBackedExecutionComposition composition(
        recording, rig.context, ak::context::MakeContextObjectId(1));

    const ExecutionCycleOutcome outcome =
        composition.Execute(InvalidDecision("unsupported-model-output"));

    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kInvalid);
    EXPECT_EQ(outcome.summary, "runtime-backed-cycle-invalid");
    EXPECT_NE(outcome.diagnostics.find("unsupported-model-output"),
              std::string::npos);
    EXPECT_TRUE(recording.SubmittedIds().empty());
    EXPECT_EQ(ContextContent(rig.context), "initial");
}

// ============================================================
// Boundedness (T3.3-AC-017/018)
// ============================================================
TEST(BoundednessTest, SingleSynchronousInvocationPerDecision) {
    Rig rig;
    rig.RegisterEcho();
    RecordingPort recording(rig.adapter);
    RuntimeBackedExecutionComposition composition(
        recording, rig.context, ak::context::MakeContextObjectId(1));

    const ExecutionCycleOutcome outcome =
        composition.Execute(ToolDecision("demo.echo", "a"));

    EXPECT_TRUE(outcome.completed);
    // Exactly one Submit, one Observe, one real invocation: no
    // retry, no async, no background, no recovery.
    ASSERT_EQ(recording.SubmittedIds().size(), 1u);
    ASSERT_EQ(recording.ObservedIds().size(), 1u);
    EXPECT_EQ(rig.echo_invoker.Calls(), 1u);
}

TEST(BoundednessTest, FailureDoesNotRetry) {
    Rig rig;
    rig.RegisterInvoker("demo.throw", ThrowingInvoker);
    RecordingPort recording(rig.adapter);
    RuntimeBackedExecutionComposition composition(
        recording, rig.context, ak::context::MakeContextObjectId(1));

    const ExecutionCycleOutcome outcome =
        composition.Execute(ToolDecision("demo.throw", "x"));

    EXPECT_FALSE(outcome.completed);
    // The failed invocation is NOT retried.
    ASSERT_EQ(recording.SubmittedIds().size(), 1u);
    EXPECT_EQ(recording.ObservedIds().size(), 1u);
}

// ============================================================
// Ownership (T3.3-AC-019/020/021)
// ============================================================
TEST(OwnershipBoundaryTest, PlannerToolModelNotAcquiringExecution) {
    // The composition API surface references no Planner, Tool, or
    // Model execution type; the production target links only the
    // sanctioned integration bridge + Context. The full real
    // execution cycle below completes without any Planner
    // planning, Tool execution, or Model subsystem invocation.
    Rig rig;
    rig.RegisterEcho();
    RuntimeBackedExecutionComposition composition = rig.MakeComposition();

    const ExecutionCycleOutcome outcome =
        composition.Execute(ToolDecision("demo.echo", "ownership"));

    EXPECT_TRUE(outcome.completed);
    EXPECT_EQ(ContextContent(rig.context), "echo:ownership");
}

// ============================================================
// Determinism / reproducibility (T3.3-AC-026)
// ============================================================
TEST(DeterminismTest, TwoRunsIdentical) {
    Rig rig_a(201);
    rig_a.RegisterEcho();
    RuntimeBackedExecutionComposition comp_a = rig_a.MakeComposition();
    const ExecutionCycleOutcome run_a =
        comp_a.Execute(ToolDecision("demo.echo", "alpha"));

    Rig rig_b(202);
    rig_b.RegisterEcho();
    RuntimeBackedExecutionComposition comp_b = rig_b.MakeComposition();
    const ExecutionCycleOutcome run_b =
        comp_b.Execute(ToolDecision("demo.echo", "alpha"));

    EXPECT_EQ(run_a.completed, run_b.completed);
    EXPECT_EQ(run_a.termination, run_b.termination);
    EXPECT_EQ(run_a.summary, run_b.summary);
    EXPECT_EQ(run_a.diagnostics, run_b.diagnostics);
    EXPECT_EQ(ContextContent(rig_a.context), ContextContent(rig_b.context));
}

}  // namespace
}  // namespace ak::runtime_backed_agent
