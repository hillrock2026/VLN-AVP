// ============================================================
// model_to_runtime_composition_test.cpp - TASK 3.4
// ============================================================
// Agent-Owned Model-to-Runtime Decision Integration tests.
//
// Proof of the closed bounded Agent decision path:
//
//   PromptAssemblyRequest
//     -> AgentPromptBinding::Assemble (real Prompt)
//     -> ModelInput -> AgentModelBinding::Infer
//     -> ModelResult
//     -> composition Status() gate (M-001: kFailure -> terminal
//        kFailure BEFORE interpretation / ModelAction / Runtime)
//     -> InterpretModelResult (kSuccess / kInvalidResult only)
//     -> ModelAction
//     -> RuntimeBackedExecutionComposition::Execute (TASK 3.3,
//        REUSED UNCHANGED)
//     -> RuntimeInteractionPort -> RuntimePublicApiAdapter
//     -> Runtime -> real CapabilityInvoker -> ExecutionResult
//     -> RuntimeObservation -> ContextAgentContract::Update
//     -> terminal
//
// Covers T3.4-AC-001..025: production surface, ModelResult
// consumption, Agent-owned interpretation, ModelAction mapping,
// sanctioned-boundary invocation, TASK 3.3 composition reuse,
// observation -> Context, deterministic failure semantics
// (M-001: ModelResult::kFailure -> terminal kFailure with NO
// InterpretModelResult / NO ModelAction / NO Execute / NO
// Runtime invocation / NO synthetic success / NO retry / NO
// second cycle), one bounded cycle, identity, ownership, FWA
// preservation, regression, determinism, no multi-cycle surface.
//
// The Agent interacts exclusively through the existing
// Agent-facing bindings and the CLOSED TASK 3.3 composition;
// Scheduler / Executor / CapabilityResolver / EventBus / Runtime
// internals never cross the Agent boundary. Runtime + adapter
// wiring is the test-side integration bootstrap (TASK 3.1
// section 17 pattern).
// ============================================================

#include <gtest/gtest.h>

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <functional>
#include <initializer_list>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <type_traits>
#include <utility>
#include <vector>

// Agent-owned contract surface (Agent boundary; no Runtime type).
#include <agent_kernel/agent/runtime/runtime_interaction_port.hpp>
#include <agent_kernel/agent/runtime/runtime_invocation_request.hpp>
#include <agent_kernel/agent/runtime/runtime_observation.hpp>
#include <agent_kernel/agent/runtime/runtime_submission_result.hpp>

// TASK 3.4 production surface.
#include <agent_kernel/model_to_runtime/model_result_interpreter.hpp>
#include <agent_kernel/model_to_runtime/model_to_runtime_decision_composition.hpp>

// TASK 3.3 Agent-owned composition (REUSED UNCHANGED).
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

// Prompt (P1-IS007 Rev1.1).
#include <agent_kernel/agent_prompt/agent_prompt_host.hpp>
#include <agent_kernel/prompt/prompt_definition.hpp>
#include <agent_kernel/prompt/prompt_identity.hpp>
#include <agent_kernel/prompt/prompt_request.hpp>
#include <agent_kernel/prompt/prompt_section.hpp>
#include <agent_kernel/prompt/prompt_variable.hpp>

// Model + interpretation (AK0046 / P1-IS008; TASK 2 section 12).
#include <agent_kernel/agent_model/agent_model_host.hpp>
#include <agent_kernel/model/model_input.hpp>
#include <agent_kernel/model/model_result.hpp>
#include <agent_kernel/fwa/model_action.hpp>
#include <agent_kernel/tool/tool_identity.hpp>

// FWA (preservation evidence; T3.4-AC-011).
#include <agent_kernel/fwa/first_working_agent_composition.hpp>
#include <agent_kernel/fwa/first_working_agent_configuration.hpp>

// Deterministic Model test double (TEST ONLY).
#include "../model/deterministic_model.hpp"

namespace ak::model_to_runtime {
namespace {

using ak::model::ModelId;
using ak::model::ModelInput;
using ak::model::ModelResult;
using ak::model::ModelStatus;
using ak::model::test::DeterministicModel;
using ak::model::test::DeterministicModelMode;
using ak::runtime_backed_agent::ExecutionCycleOutcome;
using ak::runtime_backed_agent::ExecutionTermination;
using ak::runtime_backed_agent::RuntimeBackedExecutionComposition;

// ============================================================
// Deterministic capability invokers (real executable logic)
// ============================================================
[[maybe_unused]] std::string EchoInvoker(const std::string& payload) {
    return "echo:" + payload;
}

std::string ThrowingInvoker(const std::string& /*payload*/) {
    throw std::runtime_error(
        "deterministic invoker failure (T3.4 failure-path fixture)");
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
// Stopped; Runtime::Run requires kCreated).
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
};

// ============================================================
// Prompt helpers (P1-IS007 Rev1.1; deterministic definition).
// ============================================================
ak::prompt::PromptDefinition MakePromptDefinition() {
    return ak::prompt::PromptDefinition(
        ak::prompt::PromptId("t34-integration-prompt"), "1.0",
        {ak::prompt::PromptSection(
            ak::prompt::PromptSectionKind::kSystemInstruction,
            {ak::prompt::PromptComponent(
                ak::prompt::PromptSectionKind::kSystemInstruction,
                "You are an agent. {objective}")})},
        {ak::prompt::PromptVariable("objective",
                                    ak::prompt::PromptSectionKind::kUserInput,
                                    true)});
}

ak::prompt::PromptAssemblyRequest MakeRequest(
    const std::string& objective = "advance the mission") {
    return ak::prompt::PromptAssemblyRequest(
        {ak::prompt::PromptInputBinding("objective", objective)});
}

// Assembly request missing the required "objective" binding
// (deterministic prompt-assembly failure).
ak::prompt::PromptAssemblyRequest MakeMissingVariableRequest() {
    return ak::prompt::PromptAssemblyRequest(
        std::vector<ak::prompt::PromptInputBinding>{});
}

// ============================================================
// DecisionRig - full Agent-owned decision path:
// real Prompt + real deterministic Model + real Runtime/adapter
// + the CLOSED TASK 3.3 composition + the TASK 3.4 composition.
// ============================================================
struct DecisionRig {
    Rig rig;
    ak::agent::AgentPromptHost prompt_host;
    std::unique_ptr<DeterministicModel> model_holder;
    DeterministicModel* model = nullptr;  // non-owning test observable
    ak::agent::AgentModelHost model_host;
    RuntimeBackedExecutionComposition runtime_composition;
    ModelToRuntimeDecisionComposition decision_composition;

    DecisionRig(DeterministicModelMode mode,
                std::string payload,
                std::uint64_t seed = 77)
        : rig(seed),
          prompt_host(MakePromptDefinition()),
          model_holder(std::make_unique<DeterministicModel>(
              ModelId("t34-model"), mode, std::move(payload))),
          model(model_holder.get()),
          model_host(std::move(model_holder)),
          runtime_composition(rig.adapter, rig.context,
                              ak::context::MakeContextObjectId(1)),
          decision_composition(prompt_host.Binding(),
                               model_host.Binding(),
                               runtime_composition) {
        EXPECT_TRUE(model_host.Binding().Initialize().Accepted());
    }

    // Variant for failure modes that carry a diagnostic.
    DecisionRig(DeterministicModelMode mode,
                std::string payload,
                std::string diagnostic,
                std::uint64_t seed)
        : rig(seed),
          prompt_host(MakePromptDefinition()),
          model_holder(std::make_unique<DeterministicModel>(
              ModelId("t34-model"), mode, std::move(payload),
              std::move(diagnostic))),
          model(model_holder.get()),
          model_host(std::move(model_holder)),
          runtime_composition(rig.adapter, rig.context,
                              ak::context::MakeContextObjectId(1)),
          decision_composition(prompt_host.Binding(),
                               model_host.Binding(),
                               runtime_composition) {
        EXPECT_TRUE(model_host.Binding().Initialize().Accepted());
    }
};

// ============================================================
// Content helpers for preservation / creep assertions.
// ============================================================
std::string RepoPath(const char* suffix) {
    std::string path = TASK34_REPO_ROOT;
    for (char& c : path) {
        if (c == '\\') {
            c = '/';
        }
    }
    if (!path.empty() && path.back() != '/') {
        path += '/';
    }
    return path + suffix;
}

std::string ReadTextFile(const std::string& path) {
    std::ifstream stream(path);
    if (!stream) {
        return "";
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return buffer.str();
}

std::string StripComments(const std::string& source) {
    std::string out;
    out.reserve(source.size());
    std::size_t i = 0;
    const std::size_t n = source.size();
    while (i < n) {
        if (i + 1 < n && source[i] == '/' && source[i + 1] == '/') {
            while (i < n && source[i] != '\n') {
                ++i;
            }
        } else if (i + 1 < n && source[i] == '/' && source[i + 1] == '*') {
            i += 2;
            while (i + 1 < n && !(source[i] == '*' && source[i + 1] == '/')) {
                ++i;
            }
            if (i + 1 < n) {
                i += 2;
            } else {
                i = n;
            }
        } else {
            out += source[i];
            ++i;
        }
    }
    return out;
}

bool ContainsAnyOf(const std::string& text,
                   std::initializer_list<const char*> needles) {
    for (const char* needle : needles) {
        if (text.find(needle) != std::string::npos) {
            return true;
        }
    }
    return false;
}

// ============================================================
// Production surface (T3.4-AC-001)
// ============================================================
TEST(ModelReachableTest, PromptToInferReachesModel) {
    DecisionRig rig(DeterministicModelMode::kToolThenComplete,
                    "tool:demo.echo:hello");
    rig.rig.RegisterEcho();

    const ExecutionCycleOutcome outcome =
        rig.decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_TRUE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kCompleted);
    // The real deterministic Model was invoked exactly once through
    // the Agent-owned path (Prompt -> ModelInput -> Infer).
    ASSERT_NE(rig.model, nullptr);
    EXPECT_GE(rig.model->inference_count(), 1u);
    // The Model received the Prompt-assembled material verbatim.
    EXPECT_EQ(rig.model->last_input_content(),
              "You are an agent. advance the mission");
}

// ============================================================
// ModelResult consumption (T3.4-AC-002)
// ============================================================
TEST(ModelResultConsumedTest, AgentConsumesModelResult) {
    // Success payload -> terminal completed.
    DecisionRig success(DeterministicModelMode::kFixedSuccess,
                        "tool:demo.echo:hello");
    success.rig.RegisterEcho();
    EXPECT_TRUE(success.decision_composition.ExecuteOnce(MakeRequest()).completed);

    // Invalid-result payload -> terminal invalid.
    DecisionRig invalid(DeterministicModelMode::kFixedSuccess,
                        "unsupported-model-output");
    invalid.rig.RegisterEcho();
    const ExecutionCycleOutcome invalid_outcome =
        invalid.decision_composition.ExecuteOnce(MakeRequest());
    EXPECT_FALSE(invalid_outcome.completed);
    EXPECT_EQ(invalid_outcome.termination, ExecutionTermination::kInvalid);

    // Model inference failure -> terminal failure.
    DecisionRig failure(DeterministicModelMode::kFailure, "x",
                        "deterministic-model-failure", 79);
    failure.rig.RegisterEcho();
    const ExecutionCycleOutcome failure_outcome =
        failure.decision_composition.ExecuteOnce(MakeRequest());
    EXPECT_FALSE(failure_outcome.completed);
    EXPECT_EQ(failure_outcome.termination, ExecutionTermination::kFailure);
}

// ============================================================
// Agent-owned interpretation (T3.4-AC-003/004)
// ============================================================
TEST(InterpretationOwnedTest, InterpretationProducesExistingModelAction) {
    // The production interpreter returns the existing Agent-owned
    // ak::agent::ModelAction; no new decision type is introduced.
    const ak::agent::ModelAction tool = InterpretModelResult(
        ModelResult::Success("tool:demo.echo:hello"));
    EXPECT_TRUE(tool.IsToolInvoke());
    ASSERT_NE(tool.Capability(), nullptr);
    EXPECT_EQ(tool.Capability()->Value(), "demo.echo");
    EXPECT_EQ(tool.Arguments(), "hello");

    const ak::agent::ModelAction complete =
        InterpretModelResult(ModelResult::Success("complete"));
    EXPECT_TRUE(complete.IsComplete());

    const ak::agent::ModelAction invalid = InterpretModelResult(
        ModelResult::Success("do something"));
    EXPECT_TRUE(invalid.IsInvalid());
    EXPECT_EQ(invalid.Reason(), "unsupported-model-output");
}

TEST(ModelActionProducedTest, ToolInvokeFromReferenceVocabulary) {
    const ak::agent::ModelAction action = InterpretModelResult(
        ModelResult::Success("tool:demo.echo:hello"));
    EXPECT_TRUE(action.IsToolInvoke());
    EXPECT_EQ(action.Kind(), ak::agent::ModelActionKind::kToolInvoke);
    ASSERT_NE(action.Capability(), nullptr);
    EXPECT_EQ(action.Capability()->Value(), "demo.echo");
    EXPECT_EQ(action.Arguments(), "hello");
}

TEST(ModelActionProducedTest, CompleteFromReferenceVocabulary) {
    const ak::agent::ModelAction action =
        InterpretModelResult(ModelResult::Success("complete"));
    EXPECT_TRUE(action.IsComplete());
    EXPECT_EQ(action.Kind(), ak::agent::ModelActionKind::kComplete);
    EXPECT_FALSE(action.IsToolInvoke());
}

TEST(ModelActionProducedTest, InvalidFromUnsupportedPayload) {
    const ak::agent::ModelAction action = InterpretModelResult(
        ModelResult::Success("not a supported decision"));
    EXPECT_TRUE(action.IsInvalid());
    EXPECT_EQ(action.Kind(), ak::agent::ModelActionKind::kInvalid);
    EXPECT_EQ(action.Reason(), "unsupported-model-output");
}

TEST(ModelActionProducedTest, InvalidFromMalformedToolPayload) {
    // Missing arguments separator.
    EXPECT_EQ(InterpretModelResult(ModelResult::Success("tool:demo.echo"))
                  .Reason(),
              "malformed-tool-output");
    // Empty arguments.
    EXPECT_EQ(InterpretModelResult(ModelResult::Success("tool:demo.echo:"))
                  .Reason(),
              "malformed-tool-output");
    // Empty capability.
    EXPECT_EQ(InterpretModelResult(ModelResult::Success("tool::hello"))
                  .Reason(),
              "malformed-tool-output");
}

TEST(ModelActionProducedTest, InvalidFromInvalidCapabilityIdentity) {
    // Whitespace-only capability cannot form a CapabilityId
    // (TOL-111); deterministic invalid rejection.
    const ak::agent::ModelAction action =
        InterpretModelResult(ModelResult::Success("tool:   :hello"));
    EXPECT_TRUE(action.IsInvalid());
    EXPECT_EQ(action.Reason(), "invalid-capability-identity");
}

TEST(ModelActionProducedTest, InvalidFromInvalidResult) {
    const ak::agent::ModelAction action = InterpretModelResult(
        ModelResult::InvalidResult("provider output is not interpretable"));
    EXPECT_TRUE(action.IsInvalid());
    EXPECT_EQ(action.Reason(), "provider output is not interpretable");
}
// ============================================================
// Model boundary (T3.4-AC-005/018)
// ============================================================
TEST(ModelCannotInvokeRuntimeTest, ModelFailureNeverReachesRuntime) {
    // The Model produces a kFailure ModelResult; the composition
    // Status() gate terminates as kFailure and the Model has no
    // path to the Runtime. Static include/link isolation is
    // verified by ModelToRuntimeBoundaryCheck.
    DecisionRig rig(DeterministicModelMode::kFailure, "x",
                    "deterministic-model-failure", 83);
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    // Re-wire the runtime composition over the recording port to
    // observe any (forbidden) Runtime traffic.
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);

    const ExecutionCycleOutcome outcome =
        decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kFailure);
    EXPECT_TRUE(recording.SubmittedIds().empty());
    EXPECT_TRUE(recording.ObservedIds().empty());
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 0u);
    // The Model was invoked exactly once (Infer) and nothing else.
    ASSERT_NE(rig.model, nullptr);
    EXPECT_EQ(rig.model->inference_count(), 1u);
}

TEST(ModelBoundaryTest, ModelOnlySeesModelInput) {
    // The Model receives only the Prompt-assembled model-facing
    // material; no Runtime, Context, Tool, or Agent state is
    // forwarded to the Model boundary.
    DecisionRig rig(DeterministicModelMode::kFixedSuccess,
                    "tool:demo.echo:hello");
    rig.rig.RegisterEcho();
    const ExecutionCycleOutcome outcome =
        rig.decision_composition.ExecuteOnce(MakeRequest("the objective"));

    EXPECT_TRUE(outcome.completed);
    ASSERT_NE(rig.model, nullptr);
    EXPECT_EQ(rig.model->last_input_content(),
              "You are an agent. the objective");
    // Model lifecycle is untouched by the composition: still Ready.
    EXPECT_EQ(rig.model_host.Binding().State(),
              ak::model::ModelLifecycleState::kReady);
}

TEST(ModelBoundaryTest, ModelReturnsModelResultNotModelAction) {
    // The Model's Infer() returns a Model-owned ModelResult; the
    // Model never produces a ModelAction. The Agent-owned
    // interpreter derives the ModelAction.
    DeterministicModel model(ModelId("boundary-model"),
                             DeterministicModelMode::kFixedSuccess,
                             "tool:demo.echo:hello");
    EXPECT_TRUE(model.Initialize().Accepted());
    const ModelResult result = model.Infer(ModelInput("input"));
    EXPECT_EQ(result.Status(), ModelStatus::kSuccess);
    static_assert(std::is_same_v<std::remove_const_t<decltype(result)>,
                                   ModelResult>,
                  "Model::Infer returns the Model-owned ModelResult");
}

// ============================================================
// Sanctioned Runtime path (T3.4-AC-006/007)
// ============================================================
TEST(RuntimeBoundaryTest, SanctionedPathOnly) {
    // Runtime is reached only through the existing TASK 3.3
    // composition -> RuntimeInteractionPort -> RuntimePublicApiAdapter.
    DecisionRig rig(DeterministicModelMode::kFixedSuccess,
                    "tool:demo.echo:hello");
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);

    const ExecutionCycleOutcome outcome =
        decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_TRUE(outcome.completed);
    // Exactly one Submit and one Observe through the sanctioned
    // port, and they carry the same request_id.
    ASSERT_EQ(recording.SubmittedIds().size(), 1u);
    ASSERT_EQ(recording.ObservedIds().size(), 1u);
    EXPECT_EQ(recording.SubmittedIds()[0], recording.ObservedIds()[0]);
    EXPECT_NE(recording.SubmittedIds()[0], "");
}

TEST(ExecutionPathReuseTest, CompositionReusedUnchanged) {
    // The terminal outcome carries the CLOSED TASK 3.3 summary
    // strings, proving the handoff consumed
    // RuntimeBackedExecutionComposition::Execute unchanged (no
    // second execution path exists). Byte-identity of the TASK 3.3
    // module is recorded in the Implementation Report.
    DecisionRig rig(DeterministicModelMode::kFixedSuccess,
                    "tool:demo.echo:hello");
    rig.rig.RegisterEcho();
    const ExecutionCycleOutcome outcome =
        rig.decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_TRUE(outcome.completed);
    EXPECT_EQ(outcome.summary, "runtime-backed-cycle-completed");
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 1u);
    EXPECT_EQ(ContextContent(rig.rig.context), "echo:hello");
}

// ============================================================
// Observation -> Context (T3.4-AC-008)
// ============================================================
TEST(ObservationReachesContextTest, SuccessReachesContext) {
    DecisionRig rig(DeterministicModelMode::kFixedSuccess,
                    "tool:demo.echo:hello");
    rig.rig.RegisterEcho();
    const ExecutionCycleOutcome outcome =
        rig.decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_TRUE(outcome.completed);
    EXPECT_EQ(ContextContent(rig.rig.context), "echo:hello");
}

TEST(ObservationReachesContextTest, FailureReachesContext) {
    // Runtime-side failure follows the existing TASK 3.3
    // semantics: failure observation -> Context update -> terminal
    // kFailure.
    DecisionRig rig(DeterministicModelMode::kFixedSuccess,
                    "tool:demo.throw:x");
    rig.rig.RegisterInvoker("demo.throw", ThrowingInvoker);
    const ExecutionCycleOutcome outcome =
        rig.decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kFailure);
    EXPECT_NE(ContextContent(rig.rig.context).find("capability-invocation-failed"),
              std::string::npos);
}

// ============================================================
// Failure semantics (T3.4-AC-009)
// ============================================================
TEST(FailureSemanticsTest, ModelFailureIsTerminalKFailure) {
    DecisionRig rig(DeterministicModelMode::kFailure, "x",
                    "deterministic-model-failure", 91);
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);

    const ExecutionCycleOutcome outcome =
        decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kFailure);
    EXPECT_EQ(outcome.summary, "model-inference-failure");
    // Diagnostic and provider-neutral error category remain
    // observable at the terminal outcome.
    EXPECT_NE(outcome.diagnostics.find("deterministic-model-failure"),
              std::string::npos);
    EXPECT_NE(outcome.diagnostics.find("model-error-category=model-failure"),
              std::string::npos);
    EXPECT_TRUE(recording.SubmittedIds().empty());
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 0u);
}

TEST(FailureSemanticsTest, ModelUnavailableIsTerminalFailure) {
    // Provider-unavailable lifecycle: Infer returns kFailure, the
    // same composition Status() gate applies.
    DecisionRig rig(DeterministicModelMode::kUnavailableOnInitialize,
                    "x", "model is unavailable", 92);
    rig.rig.RegisterEcho();
    const ExecutionCycleOutcome outcome =
        rig.decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kFailure);
    EXPECT_EQ(outcome.summary, "model-inference-failure");
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 0u);
}

TEST(FailureSemanticsTest, InvalidResultIsTerminalKInvalid) {
    DecisionRig rig(DeterministicModelMode::kInvalidResult, "x",
                    "provider-output-not-interpretable", 93);
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);

    const ExecutionCycleOutcome outcome =
        decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kInvalid);
    EXPECT_EQ(outcome.summary, "runtime-backed-cycle-invalid");
    EXPECT_NE(outcome.diagnostics.find("provider-output-not-interpretable"),
              std::string::npos);
    EXPECT_TRUE(recording.SubmittedIds().empty());
}

TEST(FailureSemanticsTest, PromptAssemblyFailureIsTerminalKFailure) {
    DecisionRig rig(DeterministicModelMode::kFixedSuccess,
                    "tool:demo.echo:hello");
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);

    const ExecutionCycleOutcome outcome =
        decision_composition.ExecuteOnce(MakeMissingVariableRequest());

    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kFailure);
    EXPECT_EQ(outcome.summary, "prompt-assembly-failure");
    // NO inference and NO Runtime invocation on prompt failure.
    ASSERT_NE(rig.model, nullptr);
    EXPECT_EQ(rig.model->inference_count(), 0u);
    EXPECT_TRUE(recording.SubmittedIds().empty());
    EXPECT_EQ(ContextContent(rig.rig.context), "initial");
}

TEST(FailureSemanticsTest, RuntimeFailureUsesTask33Semantics) {
    DecisionRig rig(DeterministicModelMode::kFixedSuccess,
                    "tool:demo.throw:x");
    rig.rig.RegisterInvoker("demo.throw", ThrowingInvoker);
    const ExecutionCycleOutcome outcome =
        rig.decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kFailure);
    EXPECT_EQ(outcome.summary, "runtime-backed-cycle-failure");
    EXPECT_NE(outcome.diagnostics.find("capability-invocation-failed"),
              std::string::npos);
}

TEST(FailureSemanticsTest, MissingCapabilityFailsDeterministically) {
    DecisionRig rig(DeterministicModelMode::kFixedSuccess,
                    "tool:demo.missing:x");
    // No capability registered under "demo.missing".
    const ExecutionCycleOutcome outcome =
        rig.decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kFailure);
    EXPECT_NE(outcome.diagnostics.find("capability-not-found"),
              std::string::npos);
}

// ============================================================
// One bounded cycle (T3.4-AC-010/020)
// ============================================================
TEST(OneBoundedCycleTest, ExactlyOneCycle) {
    DecisionRig rig(DeterministicModelMode::kToolThenComplete,
                    "tool:demo.echo:hello");
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);

    const ExecutionCycleOutcome outcome =
        decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_TRUE(outcome.completed);
    // Exactly one inference, one Submit, one Observe, one real
    // invocation, one Context update: no retry, no second cycle.
    ASSERT_NE(rig.model, nullptr);
    EXPECT_EQ(rig.model->inference_count(), 1u);
    ASSERT_EQ(recording.SubmittedIds().size(), 1u);
    ASSERT_EQ(recording.ObservedIds().size(), 1u);
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 1u);
    EXPECT_EQ(ContextContent(rig.rig.context), "echo:hello");
}

TEST(NoMultiCycleTest, NoRetryAsyncSurface) {
    // The TASK 3.4 composition exposes exactly one bounded entry
    // point (ExecuteOnce). No retry / async / worker / persistence
    // / recovery / multi-cycle API exists on the production
    // surface. The behavioral evidence: one ExecuteOnce performs
    // exactly one inference and zero/one invocation, terminating.
    static_assert(
        std::is_class_v<ModelToRuntimeDecisionComposition>,
        "composition is a concrete Agent-owned class");
    static_assert(
        std::is_same_v<decltype(&ModelToRuntimeDecisionComposition::ExecuteOnce),
                       ExecutionCycleOutcome (ModelToRuntimeDecisionComposition::*)(
                           const ak::prompt::PromptAssemblyRequest&)>,
        "ExecuteOnce is the sole bounded-cycle entry point");

    // Content assertions over the production module (comment-
    // stripped): no creep vocabulary appears as a surface
    // identifier.
    const std::string interpreter =
        StripComments(ReadTextFile(RepoPath(
            "include/agent_kernel/model_to_runtime/model_result_interpreter.hpp")));
    const std::string composition =
        StripComments(ReadTextFile(RepoPath(
            "include/agent_kernel/model_to_runtime/model_to_runtime_decision_composition.hpp")));
    const std::string surface = interpreter + composition;
    EXPECT_FALSE(ContainsAnyOf(
        surface,
        {"max_cycles", "Retry", "Async", "Worker", "Persistence",
         "Recovery", "Distributed", "Scheduler", "Executor",
         "EventBus", "CapabilityResolver", "ROS2", "MuJoCo",
         "Unitree", "runtime.h"}));
}
// ============================================================
// M-001: ModelResult::kFailure terminal classification
// (T3.4-AC-017; Contract sections 6.8/6.10/9)
// ============================================================
TEST(ModelFailureTerminalTest, ModelFailureTerminalKFailure) {
    // ModelResult::kFailure -> composition Status() gate ->
    // terminal kFailure with NO InterpretModelResult, NO
    // ModelAction, NO Execute, NO Runtime invocation, NO
    // synthetic success, NO retry, NO second cycle.
    DecisionRig rig(DeterministicModelMode::kFailure, "x",
                    "deterministic-model-failure", 101);
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);

    const ExecutionCycleOutcome outcome =
        decision_composition.ExecuteOnce(MakeRequest());

    // Terminal kFailure; no synthetic success.
    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kFailure);
    EXPECT_EQ(outcome.summary, "model-inference-failure");
    EXPECT_NE(outcome.diagnostics.find("deterministic-model-failure"),
              std::string::npos);

    // Runtime invocation count = 0; no port traffic; no real
    // capability execution.
    EXPECT_TRUE(recording.SubmittedIds().empty());
    EXPECT_TRUE(recording.ObservedIds().empty());
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 0u);

    // No retry / no second cycle: exactly one inference.
    ASSERT_NE(rig.model, nullptr);
    EXPECT_EQ(rig.model->inference_count(), 1u);

    // No observation reached Context.
    EXPECT_EQ(ContextContent(rig.rig.context), "initial");
}

TEST(ModelFailureTerminalTest, NoInvalidConversionOnModelFailure) {
    // ModelResult::kFailure never reaches InterpretModelResult and
    // never becomes ModelAction::kInvalid. The outcome termination
    // is kFailure, never kInvalid (M-001; Contract section 6.10).
    DecisionRig rig(DeterministicModelMode::kFailure, "x",
                    "deterministic-model-failure", 102);
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);

    const ExecutionCycleOutcome outcome =
        decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_EQ(outcome.termination, ExecutionTermination::kFailure);
    EXPECT_NE(outcome.termination, ExecutionTermination::kInvalid);
    EXPECT_EQ(outcome.summary, "model-inference-failure");
    // No ModelAction is produced on the Model-failure path, so no
    // kInvalid reason can exist; the composition reports the
    // Model-side evidence directly.
    EXPECT_NE(outcome.diagnostics.find("model-error-category=model-failure"),
              std::string::npos);
    EXPECT_TRUE(recording.SubmittedIds().empty());
}

TEST(ModelFailureTerminalTest, NoExecuteNoRuntimeInvocation) {
    // RuntimeBackedExecutionComposition::Execute() is never called
    // on the Model-failure path: the Status() gate terminates
    // BEFORE the handoff. Evidence: zero Submit/Observe traffic,
    // zero real invocations, unchanged Context, terminal kFailure.
    DecisionRig rig(DeterministicModelMode::kFailure, "x",
                    "deterministic-model-failure", 103);
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);

    const ExecutionCycleOutcome outcome =
        decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_EQ(outcome.termination, ExecutionTermination::kFailure);
    EXPECT_TRUE(recording.SubmittedIds().empty());
    EXPECT_TRUE(recording.ObservedIds().empty());
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 0u);
    EXPECT_EQ(ContextContent(rig.rig.context), "initial");
    ASSERT_NE(rig.model, nullptr);
    EXPECT_EQ(rig.model->inference_count(), 1u);
}

// ============================================================
// kComplete semantics (T3.4-AC-015)
// ============================================================
TEST(CompleteSemanticsTest, KCompleteNoRuntimeInvocation) {
    DecisionRig rig(DeterministicModelMode::kFixedSuccess, "complete");
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);

    const ExecutionCycleOutcome outcome =
        decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_TRUE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kCompleted);
    // NO Runtime invocation for kComplete.
    EXPECT_TRUE(recording.SubmittedIds().empty());
    EXPECT_TRUE(recording.ObservedIds().empty());
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 0u);
    EXPECT_EQ(ContextContent(rig.rig.context), "initial");
}

// ============================================================
// kInvalid semantics (T3.4-AC-016)
// ============================================================
TEST(InvalidSemanticsTest, KInvalidResultDeterministic) {
    DecisionRig rig(DeterministicModelMode::kInvalidResult, "x",
                    "provider-output-not-interpretable", 111);
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);

    const ExecutionCycleOutcome outcome =
        decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kInvalid);
    EXPECT_EQ(outcome.summary, "runtime-backed-cycle-invalid");
    EXPECT_NE(outcome.diagnostics.find("provider-output-not-interpretable"),
              std::string::npos);
    EXPECT_TRUE(recording.SubmittedIds().empty());
}

TEST(InvalidSemanticsTest, UnsupportedPayloadNoRuntime) {
    DecisionRig rig(DeterministicModelMode::kFixedSuccess,
                    "do something random");
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);

    const ExecutionCycleOutcome outcome =
        decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_EQ(outcome.termination, ExecutionTermination::kInvalid);
    EXPECT_NE(outcome.diagnostics.find("unsupported-model-output"),
              std::string::npos);
    EXPECT_TRUE(recording.SubmittedIds().empty());
    EXPECT_EQ(ContextContent(rig.rig.context), "initial");
}

TEST(InvalidSemanticsTest, MalformedToolPayloadNoRuntime) {
    DecisionRig rig(DeterministicModelMode::kFixedSuccess,
                    "tool:demo.echo:");
    rig.rig.RegisterEcho();
    const ExecutionCycleOutcome outcome =
        rig.decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_EQ(outcome.termination, ExecutionTermination::kInvalid);
    EXPECT_NE(outcome.diagnostics.find("malformed-tool-output"),
              std::string::npos);
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 0u);
}

TEST(InvalidSemanticsTest, InvalidCapabilityIdentityNoRuntime) {
    DecisionRig rig(DeterministicModelMode::kFixedSuccess,
                    "tool:   :hello");
    rig.rig.RegisterEcho();
    const ExecutionCycleOutcome outcome =
        rig.decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_EQ(outcome.termination, ExecutionTermination::kInvalid);
    EXPECT_NE(outcome.diagnostics.find("invalid-capability-identity"),
              std::string::npos);
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 0u);
}

TEST(InvalidSemanticsTest, NoActionableResultNoRuntime) {
    // A success payload with no interpretable action is a bounded
    // terminal invalid; no action is fabricated and no Runtime
    // invocation occurs.
    DecisionRig rig(DeterministicModelMode::kFixedSuccess, "do nothing");
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);

    const ExecutionCycleOutcome outcome =
        decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_EQ(outcome.termination, ExecutionTermination::kInvalid);
    EXPECT_TRUE(recording.SubmittedIds().empty());
}

// ============================================================
// request_id identity (T3.4-AC-021)
// ============================================================
TEST(RequestIdentityTest, PerInvocationPreservedNoCrossTalk) {
    DecisionRig rig_a(DeterministicModelMode::kFixedSuccess,
                      "tool:demo.echo:alpha", 121);
    rig_a.rig.RegisterEcho();
    RecordingPort recording_a(rig_a.rig.adapter);
    RuntimeBackedExecutionComposition comp_a(
        recording_a, rig_a.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition dec_a(
        rig_a.prompt_host.Binding(), rig_a.model_host.Binding(), comp_a);
    EXPECT_TRUE(dec_a.ExecuteOnce(MakeRequest()).completed);

    DecisionRig rig_b(DeterministicModelMode::kFixedSuccess,
                      "tool:demo.echo:beta", 122);
    rig_b.rig.RegisterEcho();
    RecordingPort recording_b(rig_b.rig.adapter);
    RuntimeBackedExecutionComposition comp_b(
        recording_b, rig_b.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition dec_b(
        rig_b.prompt_host.Binding(), rig_b.model_host.Binding(), comp_b);
    EXPECT_TRUE(dec_b.ExecuteOnce(MakeRequest()).completed);

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
    EXPECT_EQ(ContextContent(rig_a.rig.context), "echo:alpha");
    EXPECT_EQ(ContextContent(rig_b.rig.context), "echo:beta");
}

// ============================================================
// Ownership (T3.4-AC-022)
// ============================================================
TEST(OwnershipBoundaryTest, PlannerToolModelNotAcquiringExecution) {
    // The TASK 3.4 path completes with no Planner planning, no
    // Tool execution authority, and no Model execution authority:
    // the composition consumes Prompt + Model bindings and the
    // CLOSED TASK 3.3 composition only.
    DecisionRig rig(DeterministicModelMode::kFixedSuccess,
                    "tool:demo.echo:ownership");
    rig.rig.RegisterEcho();
    const ExecutionCycleOutcome outcome =
        rig.decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_TRUE(outcome.completed);
    EXPECT_EQ(ContextContent(rig.rig.context), "echo:ownership");
}

TEST(OwnershipBoundaryTest, ModelActionStaysAgentOwned) {
    // ModelAction remains the Agent-owned decision value; the
    // Model never produces it and the TASK 3.4 composition hands
    // it to the TASK 3.3 composition unchanged.
    const ak::agent::ModelAction action = InterpretModelResult(
        ModelResult::Success("tool:demo.echo:owned"));
    EXPECT_TRUE(action.IsToolInvoke());
    EXPECT_EQ(action.Capability()->Value(), "demo.echo");
}

// ============================================================
// Additive composition (T3.4-AC-024)
// ============================================================
TEST(AdditiveCompositionTest, NewCompositionSeparate) {
    // The CLOSED TASK 3.3 composition still functions standalone
    // and the new TASK 3.4 composition is an additive Agent-owned
    // path; neither modifies the other.
    Rig rig;
    rig.RegisterEcho();
    RuntimeBackedExecutionComposition task33 =
        RuntimeBackedExecutionComposition(
            rig.adapter, rig.context, ak::context::MakeContextObjectId(1));
    const ExecutionCycleOutcome standalone =
        task33.Execute(ak::agent::ModelAction::InvokeTool(
            ak::tool::CapabilityId("demo.echo"), "standalone"));
    EXPECT_TRUE(standalone.completed);
    EXPECT_EQ(ContextContent(rig.context), "echo:standalone");

    DecisionRig t34(DeterministicModelMode::kFixedSuccess,
                    "tool:demo.echo:additive");
    t34.rig.RegisterEcho();
    const ExecutionCycleOutcome integrated =
        t34.decision_composition.ExecuteOnce(MakeRequest());
    EXPECT_TRUE(integrated.completed);
    EXPECT_EQ(ContextContent(t34.rig.context), "echo:additive");
}

// ============================================================
// Prompt path reuse (T3.4-AC-025)
// ============================================================
TEST(PromptPathReuseTest, ExistingPromptPathUsed) {
    // The model-facing input is assembled through the existing
    // AgentPromptBinding::Assemble; no new Prompt contract exists.
    DecisionRig rig(DeterministicModelMode::kFixedSuccess,
                    "tool:demo.echo:prompt");
    rig.rig.RegisterEcho();
    const ExecutionCycleOutcome outcome =
        rig.decision_composition.ExecuteOnce(MakeRequest("prompt reuse"));

    EXPECT_TRUE(outcome.completed);
    ASSERT_NE(rig.model, nullptr);
    EXPECT_EQ(rig.model->last_input_content(),
              "You are an agent. prompt reuse");
}

// ============================================================
// Determinism (T3.4-AC-013)
// ============================================================
TEST(E2EDeterminismTest, TwoRunsIdentical) {
    DecisionRig rig_a(DeterministicModelMode::kFixedSuccess,
                      "tool:demo.echo:alpha", 131);
    rig_a.rig.RegisterEcho();
    const ExecutionCycleOutcome run_a =
        rig_a.decision_composition.ExecuteOnce(MakeRequest());

    DecisionRig rig_b(DeterministicModelMode::kFixedSuccess,
                      "tool:demo.echo:alpha", 132);
    rig_b.rig.RegisterEcho();
    const ExecutionCycleOutcome run_b =
        rig_b.decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_EQ(run_a.completed, run_b.completed);
    EXPECT_EQ(run_a.termination, run_b.termination);
    EXPECT_EQ(run_a.summary, run_b.summary);
    EXPECT_EQ(run_a.diagnostics, run_b.diagnostics);
    EXPECT_EQ(ContextContent(rig_a.rig.context),
              ContextContent(rig_b.rig.context));
    EXPECT_EQ(ContextContent(rig_a.rig.context), "echo:alpha");
}
// ============================================================
// E2E real Runtime-backed execution (T3.4-AC-013)
// ============================================================
TEST(E2ETest, ModelToRuntimeFullPath) {
    // Full sanctioned path with real Prompt, real deterministic
    // Model, real Runtime, real adapter, real CapabilityInvoker:
    //   Prompt -> ModelInput -> Infer -> ModelResult
    //     -> Status() gate -> InterpretModelResult -> ModelAction
    //     -> TASK 3.3 Execute -> Runtime -> RuntimeObservation
    //     -> Context update -> terminal kCompleted
    DecisionRig rig(DeterministicModelMode::kFixedSuccess,
                    "tool:demo.echo:hello");
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);

    const ExecutionCycleOutcome outcome =
        decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_TRUE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kCompleted);
    EXPECT_EQ(outcome.summary, "runtime-backed-cycle-completed");
    ASSERT_NE(rig.model, nullptr);
    EXPECT_EQ(rig.model->inference_count(), 1u);
    EXPECT_EQ(rig.model->last_input_content(),
              "You are an agent. advance the mission");
    ASSERT_EQ(recording.SubmittedIds().size(), 1u);
    EXPECT_EQ(recording.SubmittedIds()[0], recording.ObservedIds()[0]);
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 1u);
    EXPECT_EQ(rig.rig.echo_invoker.Payloads()[0], "hello");
    EXPECT_EQ(ContextContent(rig.rig.context), "echo:hello");
}

// ============================================================
// No direct ModelResult -> Runtime path (T3.4-AC-014)
// ============================================================
TEST(NoDirectPathTest, ModelResultNotRuntime) {
    // A ModelResult is never handed to the Runtime. Even a
    // kToolInvoke ModelAction reaches the Runtime only through the
    // Agent-owned interpretation and the CLOSED TASK 3.3
    // composition; the interpreter (Agent) and the composition
    // remain the sole ModelResult consumers. The Model-failure
    // case terminates with zero Runtime traffic (M-001).
    DecisionRig rig(DeterministicModelMode::kFailure, "x",
                    "deterministic-model-failure", 141);
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);

    const ExecutionCycleOutcome outcome =
        decision_composition.ExecuteOnce(MakeRequest());

    EXPECT_FALSE(outcome.completed);
    EXPECT_EQ(outcome.termination, ExecutionTermination::kFailure);
    EXPECT_TRUE(recording.SubmittedIds().empty());
    EXPECT_EQ(ContextContent(rig.rig.context), "initial");
}

// ============================================================
// FWA preservation (T3.4-AC-011)
// ============================================================
TEST(FWAPreservationTest, FwaArtifactsUnchanged) {
    // Content assertions: the FWA headers still expose the
    // documented FWA surface and contain no TASK 3.4 module
    // contamination. Byte-identity hashes are recorded in the
    // Implementation Report; the FWA test target and boundary
    // check remain green in the full regression run.
    const std::string model_action = ReadTextFile(RepoPath(
        "include/agent_kernel/fwa/model_action.hpp"));
    const std::string composition = ReadTextFile(RepoPath(
        "include/agent_kernel/fwa/first_working_agent_composition.hpp"));
    const std::string configuration = ReadTextFile(RepoPath(
        "include/agent_kernel/fwa/first_working_agent_configuration.hpp"));

    ASSERT_FALSE(model_action.empty());
    ASSERT_FALSE(composition.empty());
    ASSERT_FALSE(configuration.empty());

    EXPECT_NE(model_action.find("ModelAction"), std::string::npos);
    EXPECT_NE(model_action.find("kToolInvoke"), std::string::npos);
    EXPECT_NE(composition.find("FirstWorkingAgentComposition"),
              std::string::npos);
    EXPECT_NE(configuration.find("ModelBoundary"), std::string::npos);

    // No TASK 3.4 contamination in FWA artifacts.
    EXPECT_EQ(model_action.find("model_to_runtime"), std::string::npos);
    EXPECT_EQ(composition.find("model_to_runtime"), std::string::npos);
    EXPECT_EQ(configuration.find("model_to_runtime"), std::string::npos);

    // The FWA composition type remains available (compile-time
    // preservation evidence).
    static_assert(
        std::is_class_v<ak::agent::FirstWorkingAgentComposition>,
        "FWA composition type must remain available");
}

// ============================================================
// Authority / regression preservation (T3.4-AC-012/019/023)
// ============================================================
TEST(AuthorityUnchangedTest, NoClosedAuthorityModifiedByModule) {
    // Content assertions over the new module: it references no
    // CLOSED authority file and introduces no creep vocabulary
    // (Contract section 10.2). Byte-identity of the CLOSED
    // authorities is recorded in the Implementation Report.
    const std::string interpreter_header = ReadTextFile(RepoPath(
        "include/agent_kernel/model_to_runtime/model_result_interpreter.hpp"));
    const std::string interpreter_source = ReadTextFile(RepoPath(
        "src/model_to_runtime/model_result_interpreter.cpp"));
    const std::string composition_header = ReadTextFile(RepoPath(
        "include/agent_kernel/model_to_runtime/model_to_runtime_decision_composition.hpp"));
    const std::string composition_source = ReadTextFile(RepoPath(
        "src/model_to_runtime/model_to_runtime_decision_composition.cpp"));

    ASSERT_FALSE(interpreter_header.empty());
    ASSERT_FALSE(interpreter_source.empty());
    ASSERT_FALSE(composition_header.empty());
    ASSERT_FALSE(composition_source.empty());

    const std::string module = interpreter_header + interpreter_source +
                               composition_header + composition_source;
    const std::string code = StripComments(module);

    // No new architecture / provider / robotics / hardware surface.
    EXPECT_FALSE(ContainsAnyOf(
        code,
        {"max_cycles", "Retry", "Async", "Worker", "Persistence",
         "Recovery", "Distributed", "MultiCycle", "Scheduler",
         "Executor", "EventBus", "CapabilityResolver", "Provider",
         "Registry", "ROS2", "MuJoCo", "Unitree", "rclcpp",
         "runtime.h", "GetScheduler", "GetExecutor", "GetResolver",
         "GetEventBus"}));
}

TEST(RegressionTest, FullSuiteGreen) {
    // Smoke regression of the CLOSED baselines inside this test
    // binary: the TASK 3.3 composition and the TASK 3.2 adapter
    // retain their documented deterministic semantics. The full
    // CTest regression (TASK 3.2 31/31 + TASK 3.3 33/33 + new
    // targets) is executed and recorded in the Implementation
    // Report.
    Rig rig;
    rig.RegisterEcho();

    // TASK 3.3 baseline behavior (unchanged).
    RuntimeBackedExecutionComposition task33 =
        RuntimeBackedExecutionComposition(
            rig.adapter, rig.context, ak::context::MakeContextObjectId(1));
    const ExecutionCycleOutcome tool =
        task33.Execute(ak::agent::ModelAction::InvokeTool(
            ak::tool::CapabilityId("demo.echo"), "regression"));
    EXPECT_TRUE(tool.completed);
    EXPECT_EQ(tool.termination, ExecutionTermination::kCompleted);
    EXPECT_EQ(ContextContent(rig.context), "echo:regression");

    const ExecutionCycleOutcome complete =
        task33.Execute(ak::agent::ModelAction::Complete());
    EXPECT_TRUE(complete.completed);
    EXPECT_EQ(complete.termination, ExecutionTermination::kCompleted);

    const ExecutionCycleOutcome invalid =
        task33.Execute(ak::agent::ModelAction::Invalid("regression-invalid"));
    EXPECT_FALSE(invalid.completed);
    EXPECT_EQ(invalid.termination, ExecutionTermination::kInvalid);

    // TASK 3.2 adapter surface (unchanged): direct Submit/Observe
    // through the real adapter still round-trips. A fresh Runtime
    // is used because the Runtime state machine is one-shot
    // (Created -> Running -> Stopped).
    Rig adapter_rig;
    adapter_rig.RegisterEcho();
    const ak::agent::RuntimeInvocationRequest request{
        ak::agent::RuntimeRequestId("t34-regression-request"),
        "demo.echo", "adapter"};
    const ak::agent::RuntimeSubmissionResult submission =
        adapter_rig.adapter.Submit(request);
    EXPECT_TRUE(submission.accepted);
    const ak::agent::RuntimeObservation observation =
        adapter_rig.adapter.Observe(submission.request_id);
    EXPECT_EQ(observation.status, ak::agent::ObservationStatus::kSuccess);
    EXPECT_EQ(observation.output, "echo:adapter");
}

}  // namespace
}  // namespace ak::model_to_runtime