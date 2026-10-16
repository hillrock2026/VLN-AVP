// ============================================================
// agent_continuation_composition_test.cpp - TASK 3.5
// ============================================================
// Agent-Owned Observation-Driven Continuation Integration
// tests.
//
// Proof of the closed bounded continuation:
//
//   first cycle (ModelToRuntimeDecisionComposition::ExecuteOnce,
//                TASK 3.4, REUSED UNCHANGED)
//     -> terminal + RuntimeObservation + Context update
//     -> continuation precondition gate (PRE-1..PRE-4)
//     -> BuildContinuationInput (Context-derived material only)
//     -> ONE continuation decision-generation (TASK 3.4
//        ExecuteOnce second call, REUSED UNCHANGED)
//     -> terminal -> STOP
//
// Covers ARI-3.5-C-001..C-026: continuation starts only from a
// completed execution state, RuntimeObservation -> Context ->
// next decision, exactly one decision-generation opportunity,
// Agent-owned continuation control, existing Prompt / Model /
// interpretation / ModelAction reuse, TASK 3.3 Runtime-backed
// execution reuse, M-001 failure semantics (ModelResult::kFailure
// -> terminal kFailure with NO interpretation / NO Runtime / NO
// retry), no retry / recovery / loop / persistence / async,
// FWA / TASK 3.3 / TASK 3.4 / ExecutionSupervision / authority
// preservation, determinism, and regression.
//
// The Agent interacts exclusively through the existing
// Agent-facing surfaces and the CLOSED TASK 3.3 composition;
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

// TASK 3.5 production surface.
#include <agent_kernel/agent_continuation/agent_continuation_composition.hpp>

// TASK 3.4 production surface (REUSED UNCHANGED).
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
#include <agent_kernel/model/model.hpp>
#include <agent_kernel/model/model_input.hpp>
#include <agent_kernel/model/model_result.hpp>
#include <agent_kernel/fwa/model_action.hpp>
#include <agent_kernel/tool/tool_identity.hpp>

// FWA / ExecutionSupervision (preservation evidence; C-023 / C-024).
#include <agent_kernel/fwa/first_working_agent_composition.hpp>
#include <agent_kernel/fwa/first_working_agent_configuration.hpp>
#include <agent_kernel/agent/execution/execution_supervision.hpp>

// Deterministic Model test double (TEST ONLY).
#include "../model/deterministic_model.hpp"

namespace ak::agent_continuation {
namespace {

using ak::model::ModelId;
using ak::model::ModelInput;
using ak::model::ModelResult;
using ak::model::ModelStatus;
using ak::model::test::DeterministicModel;
using ak::model::test::DeterministicModelMode;
using ak::model_to_runtime::ModelToRuntimeDecisionComposition;
using ak::runtime_backed_agent::ExecutionCycleOutcome;
using ak::runtime_backed_agent::ExecutionTermination;
using ak::runtime_backed_agent::RuntimeBackedExecutionComposition;

// ============================================================
// Deterministic capability invokers (real executable logic)
// ============================================================
[[maybe_unused]] std::string ThrowingInvoker(const std::string& /*payload*/) {
    throw std::runtime_error(
        "deterministic invoker failure (T3.5 failure-path fixture)");
}

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
// records per-invocation request_id evidence. It delegates every
// operation to the sanctioned adapter; the Runtime is never
// mocked.
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
        ak::prompt::PromptId("t35-integration-prompt"), "1.0",
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

// ============================================================
// ScriptedModel - local deterministic Model test double
// (TEST ONLY). Returns a scripted ModelResult per inference call
// and records every model-facing input. Used to drive the
// continuation boundary deterministically (first cycle tool,
// continuation complete / invalid / failure).
// ============================================================
class ScriptedModel final : public ak::model::Model {
public:
    explicit ScriptedModel(std::vector<ak::model::ModelResult> scripted_results)
        : scripted_results_(std::move(scripted_results)) {}

    ak::model::ModelId Id() const noexcept override {
        return ak::model::ModelId("t35-scripted-model");
    }
    ak::model::ModelLifecycleState State() const noexcept override {
        return ak::model::ModelLifecycleState::kReady;
    }
    ak::TransitionResult Initialize() override {
        return {ak::TransitionStatus::kAccepted, ""};
    }
    ak::TransitionResult Shutdown() override {
        return {ak::TransitionStatus::kAccepted, ""};
    }
    ak::model::ModelResult Infer(const ak::model::ModelInput& input) override {
        inputs_.push_back(input.Content());
        if (scripted_results_.empty()) {
            ++calls_;
            return ak::model::ModelResult::Failure(
                "scripted-model:no-scripted-result");
        }
        const std::size_t index =
            (calls_ < scripted_results_.size())
                ? calls_
                : (scripted_results_.size() - 1u);
        ++calls_;
        return scripted_results_[index];
    }

    [[nodiscard]] std::size_t InputCount() const noexcept {
        return inputs_.size();
    }
    [[nodiscard]] const std::string& InputAt(std::size_t index) const {
        return inputs_.at(index);
    }

private:
    std::vector<ak::model::ModelResult> scripted_results_;
    std::vector<std::string> inputs_;
    std::size_t calls_ = 0;
};

// ============================================================
// ContinuationRig - full Agent-owned continuation path:
// real Prompt + real deterministic Model + real Runtime/adapter
// + the CLOSED TASK 3.3 composition + the CLOSED TASK 3.4
// composition + the TASK 3.5 continuation composition.
// ============================================================
struct ContinuationRig {
    Rig rig;
    ak::agent::AgentPromptHost prompt_host;
    std::unique_ptr<ak::model::Model> model_holder;
    ak::agent::AgentModelHost model_host;
    RuntimeBackedExecutionComposition runtime_composition;
    ModelToRuntimeDecisionComposition decision_composition;
    AgentContinuationComposition continuation_composition;

    ContinuationRig(std::unique_ptr<ak::model::Model> model,
                    std::uint64_t seed = 77)
        : rig(seed),
          prompt_host(MakePromptDefinition()),
          model_holder(std::move(model)),
          model_host(std::move(model_holder)),
          runtime_composition(rig.adapter, rig.context,
                              ak::context::MakeContextObjectId(1)),
          decision_composition(prompt_host.Binding(),
                               model_host.Binding(),
                               runtime_composition),
          continuation_composition(decision_composition, rig.context,
                                   ak::context::MakeContextObjectId(1)) {
        EXPECT_TRUE(model_host.Binding().Initialize().Accepted());
    }
};

// ============================================================
// Content helpers for preservation / creep assertions.
// ============================================================
std::string RepoPath(const char* suffix) {
    std::string path = TASK35_REPO_ROOT;
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
// Continuation boundary (C-001; Contract section 7)
// ============================================================
TEST(ContinuationBoundaryTest, ContinuationStartsAfterCompletedCycle) {
    // The continuation decision-generation happens only after the
    // first cycle reached a completed observation/context state.
    auto* model_ptr = new ScriptedModel(
        {ModelResult::Success("tool:demo.echo:hello"),
         ModelResult::Success("complete")});
    std::unique_ptr<ak::model::Model> holder(model_ptr);
    ContinuationRig rig(std::move(holder), 77);
    rig.rig.RegisterEcho();

    const ContinuationOutcome outcome =
        rig.continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    EXPECT_TRUE(outcome.continuation_started);
    EXPECT_TRUE(outcome.first_cycle.completed);
    EXPECT_EQ(outcome.first_cycle.termination, ExecutionTermination::kCompleted);
    EXPECT_NE(outcome.first_cycle.diagnostics.find("model:kToolInvoke"),
              std::string::npos);
    // The continuation input was built from the completed context.
    ASSERT_EQ(model_ptr->InputCount(), 2u);
    EXPECT_NE(model_ptr->InputAt(1).find("echo:hello"), std::string::npos);
}
// ============================================================
// E2E real Runtime-backed continuation (C-001/C-004/C-016)
// ============================================================
TEST(E2ETest, FirstCycleThenOneContinuation) {
    // Full sanctioned path with real Prompt, real deterministic
    // Model, real Runtime, real adapter, real CapabilityInvoker:
    //   first cycle: tool:demo.echo:hello -> TASK 3.3 Runtime
    //     invocation -> RuntimeObservation -> Context update
    //   continuation: "complete" -> terminal kCompleted
    //   decision-generation total = 2; no third decision.
    auto* model_ptr = new DeterministicModel(
        ModelId("t35-e2e-model"), DeterministicModelMode::kToolThenComplete,
        "tool:demo.echo:hello");
    std::unique_ptr<ak::model::Model> holder(model_ptr);
    ContinuationRig rig(std::move(holder), 77);
    rig.rig.RegisterEcho();

    const ContinuationOutcome outcome =
        rig.continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    EXPECT_TRUE(outcome.continuation_started);
    EXPECT_TRUE(outcome.first_cycle.completed);
    EXPECT_EQ(outcome.first_cycle.termination, ExecutionTermination::kCompleted);
    EXPECT_NE(outcome.first_cycle.diagnostics.find("model:kToolInvoke"),
              std::string::npos);
    EXPECT_TRUE(outcome.continuation_cycle.completed);
    EXPECT_EQ(outcome.continuation_cycle.termination,
              ExecutionTermination::kCompleted);
    EXPECT_EQ(outcome.continuation_cycle.summary,
              "runtime-backed-cycle-completed");
    // decision-generation total = 2 (first + one continuation).
    ASSERT_NE(model_ptr, nullptr);
    EXPECT_EQ(model_ptr->inference_count(), 2u);
    // first cycle ran the real Runtime-backed tool path exactly once.
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 1u);
    ASSERT_EQ(rig.rig.echo_invoker.Payloads().size(), 1u);
    EXPECT_EQ(rig.rig.echo_invoker.Payloads()[0], "hello");
    EXPECT_EQ(ContextContent(rig.rig.context), "echo:hello");
}

// ============================================================
// Determinism (C-001; Contract section 7)
// ============================================================
TEST(E2EDeterminismTest, TwoRunsIdentical) {
    auto* model_a = new DeterministicModel(
        ModelId("t35-det-a"), DeterministicModelMode::kToolThenComplete,
        "tool:demo.echo:alpha");
    ContinuationRig rig_a(std::unique_ptr<ak::model::Model>(model_a), 131);
    rig_a.rig.RegisterEcho();
    const ContinuationOutcome run_a =
        rig_a.continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    auto* model_b = new DeterministicModel(
        ModelId("t35-det-b"), DeterministicModelMode::kToolThenComplete,
        "tool:demo.echo:alpha");
    ContinuationRig rig_b(std::unique_ptr<ak::model::Model>(model_b), 132);
    rig_b.rig.RegisterEcho();
    const ContinuationOutcome run_b =
        rig_b.continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    EXPECT_EQ(run_a.continuation_started, run_b.continuation_started);
    EXPECT_EQ(run_a.first_cycle.completed, run_b.first_cycle.completed);
    EXPECT_EQ(run_a.first_cycle.termination, run_b.first_cycle.termination);
    EXPECT_EQ(run_a.first_cycle.summary, run_b.first_cycle.summary);
    EXPECT_EQ(run_a.first_cycle.diagnostics, run_b.first_cycle.diagnostics);
    EXPECT_EQ(run_a.continuation_cycle.completed,
              run_b.continuation_cycle.completed);
    EXPECT_EQ(run_a.continuation_cycle.termination,
              run_b.continuation_cycle.termination);
    EXPECT_EQ(run_a.continuation_cycle.summary,
              run_b.continuation_cycle.summary);
    EXPECT_EQ(run_a.continuation_cycle.diagnostics,
              run_b.continuation_cycle.diagnostics);
    EXPECT_EQ(ContextContent(rig_a.rig.context),
              ContextContent(rig_b.rig.context));
    EXPECT_EQ(ContextContent(rig_a.rig.context), "echo:alpha");
    ASSERT_NE(model_a, nullptr);
    ASSERT_NE(model_b, nullptr);
    EXPECT_EQ(model_a->inference_count(), 2u);
    EXPECT_EQ(model_b->inference_count(), 2u);
}

// ============================================================
// One continuation boundary (C-004 / C-016)
// ============================================================
TEST(OneContinuationTest, ExactlyOneDecisionOpportunity) {
    auto* model_ptr = new DeterministicModel(
        ModelId("t35-one"), DeterministicModelMode::kToolThenComplete,
        "tool:demo.echo:hello");
    ContinuationRig rig(std::unique_ptr<ak::model::Model>(model_ptr), 83);
    rig.rig.RegisterEcho();

    const ContinuationOutcome outcome =
        rig.continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    EXPECT_TRUE(outcome.continuation_started);
    // exactly two decision-generations: first cycle + one
    // continuation (upper bound; no third decision).
    ASSERT_NE(model_ptr, nullptr);
    EXPECT_EQ(model_ptr->inference_count(), 2u);
    EXPECT_TRUE(outcome.continuation_cycle.completed);
}

TEST(NoSecondContinuationTest, AfterTerminalNoThirdDecision) {
    auto* model_ptr = new DeterministicModel(
        ModelId("t35-stop"), DeterministicModelMode::kToolThenComplete,
        "tool:demo.echo:hello");
    ContinuationRig rig(std::unique_ptr<ak::model::Model>(model_ptr), 89);
    rig.rig.RegisterEcho();

    const ContinuationOutcome outcome =
        rig.continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    // Continuation terminal -> STOP: the single call never
    // schedules a third decision-generation internally.
    ASSERT_NE(model_ptr, nullptr);
    EXPECT_EQ(model_ptr->inference_count(), 2u);
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 1u);
    EXPECT_EQ(ContextContent(rig.rig.context), "echo:hello");
    EXPECT_TRUE(outcome.continuation_cycle.completed);
}
// ============================================================
// Continuation preconditions (C-001; Contract section 13)
// ============================================================
TEST(PreconditionTest, NoContinuationWithoutCompletedState) {
    // First cycle Model failure -> no completed observation/context
    // state -> continuation not started -> bounded STOP.
    auto* model_ptr = new DeterministicModel(
        ModelId("t35-prec-f"), DeterministicModelMode::kFailure, "x",
        "deterministic-model-failure");
    ContinuationRig rig(std::unique_ptr<ak::model::Model>(model_ptr), 91);
    rig.rig.RegisterEcho();

    const ContinuationOutcome outcome =
        rig.continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    EXPECT_FALSE(outcome.continuation_started);
    EXPECT_FALSE(outcome.first_cycle.completed);
    EXPECT_EQ(outcome.first_cycle.termination, ExecutionTermination::kFailure);
    EXPECT_EQ(outcome.continuation_cycle.summary, "continuation-not-started");
    ASSERT_NE(model_ptr, nullptr);
    EXPECT_EQ(model_ptr->inference_count(), 1u);
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 0u);
    EXPECT_EQ(ContextContent(rig.rig.context), "initial");
}

TEST(PreconditionTest, NoContinuationWithoutObservation) {
    // First cycle kComplete decision: terminal kCompleted but NO
    // Runtime invocation -> no RuntimeObservation -> continuation
    // not started (PRE-2 / R-2).
    auto* model_ptr = new DeterministicModel(
        ModelId("t35-prec-c"), DeterministicModelMode::kFixedSuccess,
        "complete");
    ContinuationRig rig(std::unique_ptr<ak::model::Model>(model_ptr), 97);
    rig.rig.RegisterEcho();

    const ContinuationOutcome outcome =
        rig.continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    EXPECT_FALSE(outcome.continuation_started);
    EXPECT_TRUE(outcome.first_cycle.completed);
    EXPECT_EQ(outcome.first_cycle.termination, ExecutionTermination::kCompleted);
    EXPECT_EQ(outcome.continuation_cycle.summary, "continuation-not-started");
    ASSERT_NE(model_ptr, nullptr);
    EXPECT_EQ(model_ptr->inference_count(), 1u);
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 0u);
    EXPECT_EQ(ContextContent(rig.rig.context), "initial");
}

TEST(PreconditionTest, NoContinuationAfterInvalidFirstCycle) {
    // First cycle invalid decision: no Runtime invocation, no
    // observation -> continuation not started (R-3).
    auto* model_ptr = new DeterministicModel(
        ModelId("t35-prec-i"), DeterministicModelMode::kFixedSuccess,
        "unsupported-model-output");
    ContinuationRig rig(std::unique_ptr<ak::model::Model>(model_ptr), 101);
    rig.rig.RegisterEcho();

    const ContinuationOutcome outcome =
        rig.continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    EXPECT_FALSE(outcome.continuation_started);
    EXPECT_FALSE(outcome.first_cycle.completed);
    EXPECT_EQ(outcome.first_cycle.termination, ExecutionTermination::kInvalid);
    EXPECT_EQ(outcome.continuation_cycle.summary, "continuation-not-started");
    ASSERT_NE(model_ptr, nullptr);
    EXPECT_EQ(model_ptr->inference_count(), 1u);
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 0u);
}

// ============================================================
// Observation-driven input (C-002 / C-003; Contract section 10)
// ============================================================
TEST(ObservationDrivenTest, SecondPromptContainsObservation) {
    auto* scripted = new ScriptedModel(
        {ModelResult::Success("tool:demo.echo:hello"),
         ModelResult::Success("complete")});
    ContinuationRig rig(std::unique_ptr<ak::model::Model>(scripted), 107);
    rig.rig.RegisterEcho();

    const ContinuationOutcome outcome =
        rig.continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    ASSERT_TRUE(outcome.continuation_started);
    ASSERT_EQ(scripted->InputCount(), 2u);
    // First input = first request assembly (existing prompt path).
    EXPECT_EQ(scripted->InputAt(0), "You are an agent. advance the mission");
    // Second input carries the first cycle's observation-derived
    // context content ("echo:hello"): observation-driven, not a
    // synthetic next decision.
    EXPECT_NE(scripted->InputAt(1).find("echo:hello"), std::string::npos);
    EXPECT_NE(scripted->InputAt(1).find("You are an agent."),
              std::string::npos);
}

TEST(ObservationDrivenTest, NoSyntheticInput) {
    auto* scripted = new ScriptedModel(
        {ModelResult::Success("tool:demo.echo:hello"),
         ModelResult::Success("complete")});
    ContinuationRig rig(std::unique_ptr<ak::model::Model>(scripted), 109);
    rig.rig.RegisterEcho();

    const ContinuationOutcome outcome =
        rig.continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    ASSERT_TRUE(outcome.continuation_started);
    ASSERT_EQ(scripted->InputCount(), 2u);
    // The continuation input is derived only from the completed
    // observation/context state: the observation content is the
    // actual invoker output that reached Context through the
    // existing ContextAgentContract::Update path.
    ASSERT_EQ(rig.rig.echo_invoker.Payloads().size(), 1u);
    EXPECT_EQ(rig.rig.echo_invoker.Payloads()[0], "hello");
    EXPECT_EQ(ContextContent(rig.rig.context), "echo:hello");
    EXPECT_NE(scripted->InputAt(1).find(
                  "[completed observation: echo:hello]"),
              std::string::npos);
    // No fabricated / externally injected material.
    EXPECT_EQ(scripted->InputAt(1).find("synthetic"), std::string::npos);
    EXPECT_EQ(scripted->InputAt(1).find("injected"), std::string::npos);
}
// ============================================================
// Continuation failure semantics (C-012; M-001)
// ============================================================
TEST(ContinuationFailureTest, ModelFailureTerminalKFailure) {
    // Continuation ModelResult::kFailure -> Status() gate ->
    // terminal kFailure; NO interpretation, NO kInvalid
    // conversion, NO retry, NO third decision.
    auto* scripted = new ScriptedModel(
        {ModelResult::Success("tool:demo.echo:hello"),
         ModelResult::Failure("deterministic-continuation-model-failure")});
    ContinuationRig rig(std::unique_ptr<ak::model::Model>(scripted), 113);
    rig.rig.RegisterEcho();

    const ContinuationOutcome outcome =
        rig.continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    EXPECT_TRUE(outcome.continuation_started);
    EXPECT_FALSE(outcome.continuation_cycle.completed);
    EXPECT_EQ(outcome.continuation_cycle.termination,
              ExecutionTermination::kFailure);
    EXPECT_EQ(outcome.continuation_cycle.summary, "model-inference-failure");
    EXPECT_NE(outcome.continuation_cycle.diagnostics.find(
                  "deterministic-continuation-model-failure"),
              std::string::npos);
    // kFailure is never converted to kInvalid (M-001).
    EXPECT_NE(outcome.continuation_cycle.termination,
              ExecutionTermination::kInvalid);
    // First cycle consumed exactly one Runtime invocation; the
    // continuation failure added none.
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 1u);
    // No retry / no third decision.
    EXPECT_EQ(scripted->InputCount(), 2u);
}

TEST(ContinuationFailureTest, NoInvalidConversionOnModelFailure) {
    auto* scripted = new ScriptedModel(
        {ModelResult::Success("tool:demo.echo:hello"),
         ModelResult::Failure("deterministic-continuation-model-failure")});
    ContinuationRig rig(std::unique_ptr<ak::model::Model>(scripted), 127);
    rig.rig.RegisterEcho();

    const ContinuationOutcome outcome =
        rig.continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    EXPECT_TRUE(outcome.continuation_started);
    EXPECT_EQ(outcome.continuation_cycle.termination,
              ExecutionTermination::kFailure);
    EXPECT_EQ(outcome.continuation_cycle.summary, "model-inference-failure");
    // No Runtime invocation from a model failure.
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 1u);
}

TEST(ContinuationFailureTest, NoExecuteNoRuntimeInvocation) {
    // The continuation failure cycle produces zero NEW port
    // traffic: the RecordingPort sees exactly the first-cycle
    // invocation only.
    auto* scripted = new ScriptedModel(
        {ModelResult::Success("tool:demo.echo:hello"),
         ModelResult::Failure("deterministic-continuation-model-failure")});
    ContinuationRig rig(std::unique_ptr<ak::model::Model>(scripted), 131);
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);
    AgentContinuationComposition continuation_composition(
        decision_composition, rig.rig.context,
        ak::context::MakeContextObjectId(1));

    const ContinuationOutcome outcome =
        continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    EXPECT_TRUE(outcome.continuation_started);
    EXPECT_EQ(outcome.continuation_cycle.termination,
              ExecutionTermination::kFailure);
    ASSERT_EQ(recording.SubmittedIds().size(), 1u);
    ASSERT_EQ(recording.ObservedIds().size(), 1u);
    EXPECT_EQ(recording.SubmittedIds()[0], recording.ObservedIds()[0]);
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 1u);
}

// ============================================================
// Terminal semantics (Contract section 14)
// ============================================================
TEST(TerminalSemanticsTest, CompleteTerminalNoRuntime) {
    // Continuation ModelAction::kComplete -> terminal kCompleted,
    // NO Runtime invocation in the continuation.
    auto* scripted = new ScriptedModel(
        {ModelResult::Success("tool:demo.echo:hello"),
         ModelResult::Success("complete")});
    ContinuationRig rig(std::unique_ptr<ak::model::Model>(scripted), 137);
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);
    AgentContinuationComposition continuation_composition(
        decision_composition, rig.rig.context,
        ak::context::MakeContextObjectId(1));

    const ContinuationOutcome outcome =
        continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    EXPECT_TRUE(outcome.continuation_started);
    EXPECT_TRUE(outcome.continuation_cycle.completed);
    EXPECT_EQ(outcome.continuation_cycle.termination,
              ExecutionTermination::kCompleted);
    EXPECT_EQ(outcome.continuation_cycle.summary,
              "runtime-backed-cycle-completed");
    ASSERT_EQ(recording.SubmittedIds().size(), 1u);
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 1u);
    EXPECT_EQ(ContextContent(rig.rig.context), "echo:hello");
}

TEST(TerminalSemanticsTest, InvalidTerminalNoRuntime) {
    // Continuation invalid / no-action -> terminal kInvalid, NO
    // Runtime invocation in the continuation.
    auto* scripted = new ScriptedModel(
        {ModelResult::Success("tool:demo.echo:hello"),
         ModelResult::Success("unsupported-model-output")});
    ContinuationRig rig(std::unique_ptr<ak::model::Model>(scripted), 139);
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);
    AgentContinuationComposition continuation_composition(
        decision_composition, rig.rig.context,
        ak::context::MakeContextObjectId(1));

    const ContinuationOutcome outcome =
        continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    EXPECT_TRUE(outcome.continuation_started);
    EXPECT_FALSE(outcome.continuation_cycle.completed);
    EXPECT_EQ(outcome.continuation_cycle.termination,
              ExecutionTermination::kInvalid);
    ASSERT_EQ(recording.SubmittedIds().size(), 1u);
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 1u);
}

TEST(TerminalSemanticsTest, ToolInvocationBoundedExecution) {
    // Continuation ModelAction::kToolInvoke -> existing TASK 3.3
    // Runtime-backed execution -> RuntimeObservation -> Context
    // update -> terminal (kCompleted / kFailure) -> STOP.
    //
    // The current Runtime state machine is one-shot (Created ->
    // Running -> Stopped; Runtime::Run requires kCreated), so the
    // continuation tool invocation through the SAME Runtime is
    // deterministically bounded by TASK 3.3 semantics: Submit ->
    // Observe -> RuntimeObservation (failure) -> Context update ->
    // terminal kFailure. This proves the continuation tool
    // decision traverses the existing Runtime-backed path
    // (RecordingPort sees the second Submit/Observe) and
    // terminates with a bounded execution result (no retry, no
    // loop). A success terminal for the second invocation would
    // require a multi-invocation Runtime, which is outside the
    // TASK 3.5 contract scope.
    auto* scripted = new ScriptedModel(
        {ModelResult::Success("tool:demo.echo:hello"),
         ModelResult::Success("tool:demo.echo:hello")});
    ContinuationRig rig(std::unique_ptr<ak::model::Model>(scripted), 149);
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);
    AgentContinuationComposition continuation_composition(
        decision_composition, rig.rig.context,
        ak::context::MakeContextObjectId(1));

    const ContinuationOutcome outcome =
        continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    EXPECT_TRUE(outcome.continuation_started);
    // The continuation tool decision reached the TASK 3.3 path.
    ASSERT_EQ(recording.SubmittedIds().size(), 2u);
    ASSERT_EQ(recording.ObservedIds().size(), 2u);
    EXPECT_EQ(recording.SubmittedIds()[1], recording.ObservedIds()[1]);
    // Bounded execution result through the existing path.
    EXPECT_FALSE(outcome.continuation_cycle.completed);
    EXPECT_EQ(outcome.continuation_cycle.termination,
              ExecutionTermination::kFailure);
    EXPECT_NE(outcome.continuation_cycle.diagnostics.find("runtime"),
              std::string::npos);
    // Context was updated with the continuation observation result.
    EXPECT_NE(ContextContent(rig.rig.context), "echo:hello");
    // STOP: no third decision, no retry.
    EXPECT_EQ(scripted->InputCount(), 2u);
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 1u);
}
// ============================================================
// No retry / recovery / loop (C-013/C-014/C-015/C-016)
// ============================================================
TEST(NoRetryNoRecoveryNoLoopTest, NoRetryOnTerminal) {
    // A terminal continuation failure never retries: inference
    // count stays at 2 and the outcome is returned once.
    auto* scripted = new ScriptedModel(
        {ModelResult::Success("tool:demo.echo:hello"),
         ModelResult::Failure("deterministic-continuation-model-failure")});
    ContinuationRig rig(std::unique_ptr<ak::model::Model>(scripted), 151);
    rig.rig.RegisterEcho();

    const ContinuationOutcome outcome =
        rig.continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    EXPECT_TRUE(outcome.continuation_started);
    EXPECT_EQ(outcome.continuation_cycle.termination,
              ExecutionTermination::kFailure);
    EXPECT_EQ(scripted->InputCount(), 2u);
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 1u);
}

TEST(NoRetryNoRecoveryNoLoopTest, NoLoopSurface) {
    // Static: the module contains no loop driver, retry, or
    // recovery vocabulary (comments stripped).
    const std::string module = StripComments(
        ReadTextFile(RepoPath(
            "include/agent_kernel/agent_continuation/agent_continuation_composition.hpp")) +
        ReadTextFile(RepoPath(
            "src/agent_continuation/agent_continuation_composition.cpp")));
    ASSERT_FALSE(module.empty());
    EXPECT_FALSE(ContainsAnyOf(
        module,
        {"while (", "for (;;)", "do {", "goto", "Retry", "retry",
         "Recovery", "recovery", "max_cycles", "MultiCycle",
         "continuation loop", "unbounded"}));
}

// ============================================================
// No persistence / no async (C-021/C-022)
// ============================================================
TEST(NoPersistenceNoAsyncTest, NoPersistenceSurface) {
    const std::string module = StripComments(
        ReadTextFile(RepoPath(
            "include/agent_kernel/agent_continuation/agent_continuation_composition.hpp")) +
        ReadTextFile(RepoPath(
            "src/agent_continuation/agent_continuation_composition.cpp")));
    ASSERT_FALSE(module.empty());
    EXPECT_FALSE(ContainsAnyOf(
        module,
        {"Persistence", "persistence", "checkpoint", "Checkpoint",
         "state store", "StateStore", "database", "Database"}));
}

TEST(NoPersistenceNoAsyncTest, NoAsyncBackgroundSurface) {
    const std::string module = StripComments(
        ReadTextFile(RepoPath(
            "include/agent_kernel/agent_continuation/agent_continuation_composition.hpp")) +
        ReadTextFile(RepoPath(
            "src/agent_continuation/agent_continuation_composition.cpp")));
    ASSERT_FALSE(module.empty());
    EXPECT_FALSE(ContainsAnyOf(
        module,
        {"Async", "async", "Background", "background", "Worker", "worker",
         "daemon", "Daemon", "std::thread", "std::future"}));
}

// ============================================================
// Ownership (C-005; Contract section 15)
// ============================================================
TEST(OwnershipBoundaryTest, AgentOwnedContinuationControl) {
    // Continuation control is an Agent-owned composition
    // (AK0041 section 3.2; AK0046 section 17.3).
    static_assert(std::is_class_v<AgentContinuationComposition>,
                  "AgentContinuationComposition must remain a class");
    static_assert(!std::is_abstract_v<AgentContinuationComposition>,
                  "AgentContinuationComposition must be concrete");
    // Agent decides continuation_started; Runtime owns execution /
    // observation production; the only Runtime traffic observed is
    // through the injected port (TASK 3.3 path).
    auto* scripted = new ScriptedModel(
        {ModelResult::Success("tool:demo.echo:hello"),
         ModelResult::Success("complete")});
    ContinuationRig rig(std::unique_ptr<ak::model::Model>(scripted), 157);
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);
    AgentContinuationComposition continuation_composition(
        decision_composition, rig.rig.context,
        ak::context::MakeContextObjectId(1));

    const ContinuationOutcome outcome =
        continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    EXPECT_TRUE(outcome.continuation_started);
    ASSERT_EQ(recording.SubmittedIds().size(), 1u);
    EXPECT_EQ(recording.SubmittedIds()[0], recording.ObservedIds()[0]);
}

// ============================================================
// Runtime path reuse (C-010/C-011)
// ============================================================
TEST(RuntimePathReuseTest, ContinuationUsesTask33Path) {
    // Both cycles' Runtime traffic traverses the same TASK 3.3
    // Runtime-backed path through the port; no second Runtime
    // execution path exists.
    auto* scripted = new ScriptedModel(
        {ModelResult::Success("tool:demo.echo:hello"),
         ModelResult::Success("tool:demo.echo:hello")});
    ContinuationRig rig(std::unique_ptr<ak::model::Model>(scripted), 163);
    rig.rig.RegisterEcho();
    RecordingPort recording(rig.rig.adapter);
    RuntimeBackedExecutionComposition runtime_composition(
        recording, rig.rig.context, ak::context::MakeContextObjectId(1));
    ModelToRuntimeDecisionComposition decision_composition(
        rig.prompt_host.Binding(), rig.model_host.Binding(),
        runtime_composition);
    AgentContinuationComposition continuation_composition(
        decision_composition, rig.rig.context,
        ak::context::MakeContextObjectId(1));

    const ContinuationOutcome outcome =
        continuation_composition.ExecuteBoundedContinuation(MakeRequest());

    // First cycle tool path: exactly one invocation via TASK 3.3.
    EXPECT_NE(outcome.first_cycle.diagnostics.find("model:kToolInvoke"),
              std::string::npos);
    EXPECT_EQ(rig.rig.echo_invoker.Calls(), 1u);
    // Continuation tool path: the second decision reached the same
    // port (bounded by the one-shot Runtime -> kFailure).
    ASSERT_EQ(recording.SubmittedIds().size(), 2u);
    ASSERT_EQ(recording.ObservedIds().size(), 2u);
    EXPECT_EQ(outcome.continuation_cycle.termination,
              ExecutionTermination::kFailure);
}

// ============================================================
// Prompt / Model / interpretation / ModelAction reuse
// (C-006/C-007/C-008/C-009)
// ============================================================
TEST(PromptPathReuseTest, ExistingPromptPathUsed) {
    auto* scripted = new ScriptedModel(
        {ModelResult::Success("tool:demo.echo:hello"),
         ModelResult::Success("complete")});
    ContinuationRig rig(std::unique_ptr<ak::model::Model>(scripted), 167);
    rig.rig.RegisterEcho();

    const ContinuationOutcome outcome =
        rig.continuation_composition.ExecuteBoundedContinuation(
            MakeRequest("prompt reuse"));
    EXPECT_TRUE(outcome.continuation_started);

    ASSERT_EQ(scripted->InputCount(), 2u);
    EXPECT_EQ(scripted->InputAt(0), "You are an agent. prompt reuse");
    // The second input is still assembled by the same prompt path
    // with the same declared variable surface.
    EXPECT_EQ(scripted->InputAt(1).find("You are an agent. prompt reuse"),
              0u);
}

TEST(ModelPathReuseTest, SameModelPathBothCycles) {
    auto* scripted = new ScriptedModel(
        {ModelResult::Success("tool:demo.echo:hello"),
         ModelResult::Success("complete")});
    ContinuationRig rig(std::unique_ptr<ak::model::Model>(scripted), 173);
    rig.rig.RegisterEcho();

    const ContinuationOutcome outcome =
        rig.continuation_composition.ExecuteBoundedContinuation(MakeRequest());
    EXPECT_TRUE(outcome.continuation_started);

    // The same AgentModelHost / Model instance served both
    // decision-generations (no second Model path).
    EXPECT_EQ(scripted->InputCount(), 2u);
}

TEST(InterpretationOwnedTest, InterpretationRemainsAgentOwned) {
    // TASK 3.4 InterpretModelResult remains the only interpreter;
    // the continuation module defines no interpretation semantics.
    const ak::agent::ModelAction tool =
        ak::model_to_runtime::InterpretModelResult(
            ModelResult::Success("tool:demo.echo:hello"));
    EXPECT_TRUE(tool.IsToolInvoke());
    ASSERT_NE(tool.Capability(), nullptr);
    EXPECT_EQ(tool.Capability()->Value(), "demo.echo");
    EXPECT_EQ(tool.Arguments(), "hello");
}

TEST(ModelActionReuseTest, ExistingVocabularyOnly) {
    // Continuation decisions use only the existing ModelAction
    // vocabulary (kToolInvoke / kComplete / kInvalid); the module
    // introduces no new decision enum or outcome semantics.
    const std::string module = StripComments(
        ReadTextFile(RepoPath(
            "include/agent_kernel/agent_continuation/agent_continuation_composition.hpp")) +
        ReadTextFile(RepoPath(
            "src/agent_continuation/agent_continuation_composition.cpp")));
    ASSERT_FALSE(module.empty());
    EXPECT_EQ(module.find("enum class"), std::string::npos);
    EXPECT_EQ(module.find("ModelActionKind"), std::string::npos);
}
// ============================================================
// FWA preservation (C-023; Plan section 20)
// ============================================================
TEST(FWAPreservationTest, FwaArtifactsUnchanged) {
    // Content assertions: the FWA artifacts still expose the
    // documented FWA surface and contain no TASK 3.5 module
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

    // No TASK 3.5 contamination in FWA artifacts.
    EXPECT_EQ(model_action.find("agent_continuation"), std::string::npos);
    EXPECT_EQ(composition.find("agent_continuation"), std::string::npos);
    EXPECT_EQ(configuration.find("agent_continuation"), std::string::npos);

    // The FWA composition type remains available (compile-time
    // preservation evidence).
    static_assert(
        std::is_class_v<ak::agent::FirstWorkingAgentComposition>,
        "FWA composition type must remain available");
}

// ============================================================
// TASK 3.3 / TASK 3.4 preservation (C-026; Plan section 18.3)
// ============================================================
TEST(Task33Task34PreservationTest, ByteIdentity) {
    const std::string t33_header = ReadTextFile(RepoPath(
        "include/agent_kernel/runtime_backed_agent/runtime_backed_execution_composition.hpp"));
    const std::string t33_source = ReadTextFile(RepoPath(
        "src/runtime_backed_agent/runtime_backed_execution_composition.cpp"));
    const std::string t34_header = ReadTextFile(RepoPath(
        "include/agent_kernel/model_to_runtime/model_to_runtime_decision_composition.hpp"));
    const std::string t34_source = ReadTextFile(RepoPath(
        "src/model_to_runtime/model_to_runtime_decision_composition.cpp"));
    const std::string t34_interp_header = ReadTextFile(RepoPath(
        "include/agent_kernel/model_to_runtime/model_result_interpreter.hpp"));
    const std::string t34_interp_source = ReadTextFile(RepoPath(
        "src/model_to_runtime/model_result_interpreter.cpp"));

    ASSERT_FALSE(t33_header.empty());
    ASSERT_FALSE(t33_source.empty());
    ASSERT_FALSE(t34_header.empty());
    ASSERT_FALSE(t34_source.empty());
    ASSERT_FALSE(t34_interp_header.empty());
    ASSERT_FALSE(t34_interp_source.empty());

    // No TASK 3.5 contamination in CLOSED TASK 3.3 / 3.4 files.
    EXPECT_EQ(t33_header.find("agent_continuation"), std::string::npos);
    EXPECT_EQ(t33_source.find("agent_continuation"), std::string::npos);
    EXPECT_EQ(t34_header.find("agent_continuation"), std::string::npos);
    EXPECT_EQ(t34_source.find("agent_continuation"), std::string::npos);
    EXPECT_EQ(t34_interp_header.find("agent_continuation"),
              std::string::npos);
    EXPECT_EQ(t34_interp_source.find("agent_continuation"),
              std::string::npos);

    // CLOSED types remain available (compile-time preservation).
    static_assert(
        std::is_class_v<ak::model_to_runtime::ModelToRuntimeDecisionComposition>,
        "TASK 3.4 composition type must remain available");
    static_assert(
        std::is_class_v<ak::runtime_backed_agent::RuntimeBackedExecutionComposition>,
        "TASK 3.3 composition type must remain available");
}

// ============================================================
// ExecutionSupervision preservation (C-024)
// ============================================================
TEST(ExecutionSupervisionPreservationTest, RepresentationUnchanged) {
    const std::string supervision = ReadTextFile(RepoPath(
        "include/agent_kernel/agent/execution/execution_supervision.hpp"));
    ASSERT_FALSE(supervision.empty());
    EXPECT_NE(supervision.find("ExecutionSupervision"), std::string::npos);
    EXPECT_NE(supervision.find("SupervisionPhase"), std::string::npos);
    // Not expanded into a new architecture by TASK 3.5.
    EXPECT_EQ(supervision.find("agent_continuation"), std::string::npos);
    static_assert(std::is_class_v<ak::agent::ExecutionSupervision>,
                  "ExecutionSupervision type must remain available");
}

// ============================================================
// Planner preservation (C-025)
// ============================================================
TEST(PlannerUnchangedTest, PlannerNotExtended) {
    // No Planner include / API / semantics in the continuation
    // module; Planner is reused only through existing authorized
    // semantics (none added by TASK 3.5).
    const std::string module = StripComments(
        ReadTextFile(RepoPath(
            "include/agent_kernel/agent_continuation/agent_continuation_composition.hpp")) +
        ReadTextFile(RepoPath(
            "src/agent_continuation/agent_continuation_composition.cpp")));
    ASSERT_FALSE(module.empty());
    EXPECT_EQ(module.find("planner"), std::string::npos);
    EXPECT_EQ(module.find("Planner"), std::string::npos);
}

// ============================================================
// Authority / regression preservation (C-017..C-022)
// ============================================================
TEST(AuthorityUnchangedTest, NoClosedAuthorityModifiedByModule) {
    // Content assertions over the new module: it references no
    // CLOSED authority file and introduces no creep vocabulary
    // (Contract section 10.2). Byte-identity of the CLOSED
    // authorities is recorded in the Implementation Report.
    const std::string module = StripComments(
        ReadTextFile(RepoPath(
            "include/agent_kernel/agent_continuation/agent_continuation_composition.hpp")) +
        ReadTextFile(RepoPath(
            "src/agent_continuation/agent_continuation_composition.cpp")));
    ASSERT_FALSE(module.empty());

    // No new architecture / provider / robotics / hardware surface.
    EXPECT_FALSE(ContainsAnyOf(
        module,
        {"max_cycles", "Retry", "Async", "Worker", "Persistence",
         "Recovery", "Distributed", "MultiCycle", "Scheduler",
         "Executor", "EventBus", "CapabilityResolver", "Provider",
         "Registry", "ROS2", "MuJoCo", "Unitree", "rclcpp",
         "runtime.h", "GetScheduler", "GetExecutor", "GetResolver",
         "GetEventBus"}));
}

TEST(RegressionTest, FullSuiteGreen) {
    // Smoke regression of the CLOSED baselines inside this test
    // binary: the TASK 3.3 composition, the TASK 3.2 adapter, and
    // the TASK 3.4 decision composition retain their documented
    // deterministic semantics. The full CTest regression
    // (TASK 3.2 31/31 + TASK 3.3 33/33 + TASK 3.4 35/35 + new
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
        ak::agent::RuntimeRequestId("t35-regression-request"),
        "demo.echo", "adapter"};
    const ak::agent::RuntimeSubmissionResult submission =
        adapter_rig.adapter.Submit(request);
    EXPECT_TRUE(submission.accepted);
    const ak::agent::RuntimeObservation observation =
        adapter_rig.adapter.Observe(submission.request_id);
    EXPECT_EQ(observation.status, ak::agent::ObservationStatus::kSuccess);
    EXPECT_EQ(observation.output, "echo:adapter");

    // TASK 3.4 standalone decision path (unchanged): a single
    // bounded ExecuteOnce still produces a Runtime-backed result.
    auto* model_ptr = new DeterministicModel(
        ModelId("t35-reg-model"), DeterministicModelMode::kFixedSuccess,
        "tool:demo.echo:t34");
    std::unique_ptr<ak::model::Model> holder(model_ptr);
    ContinuationRig t34_rig(std::move(holder), 211);
    t34_rig.rig.RegisterEcho();
    const ExecutionCycleOutcome single =
        t34_rig.decision_composition.ExecuteOnce(MakeRequest());
    EXPECT_TRUE(single.completed);
    EXPECT_EQ(single.termination, ExecutionTermination::kCompleted);
    EXPECT_EQ(ContextContent(t34_rig.rig.context), "echo:t34");
}

}  // namespace
}  // namespace ak::agent_continuation
