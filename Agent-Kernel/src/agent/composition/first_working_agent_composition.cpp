// ============================================================
// Agent Kernel - FirstWorkingAgentComposition implementation
// ============================================================
// First Working Agent Sprint 鈥?TASK 6 Rev2 搂13-搂24.
//
// This is the Agent-owned sequential composition driver. It is
// NOT a Runtime loop, Scheduler, Executor, or second Agent
// lifecycle (INV-002, INV-007, INV-008, INV-018). Every
// subsystem operation is composition over existing public APIs;
// subsystem ownership and lifecycle authority remain with the
// owning subsystem.
//
// Tool path (governance decision 搂9A): the composition owns the
// existing ak::tool::Tool root and constructs AgentToolBinding
// at construction; deterministic providers are injected via
// FirstWorkingAgentConfiguration::tool_providers and registered
// during Initialize() through Tool::Providers().Register(...).
// No AgentToolHost is used; no Tool() accessor exists (INV-025).
//
// FWA-T7 / TASK-6-Rev2 / STEP-03..STEP-12
// ============================================================

#include <agent_kernel/fwa/first_working_agent_composition.hpp>

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

#include <agent_kernel/context/context_identity.hpp>
#include <agent_kernel/context/context_objects.hpp>
#include <agent_kernel/foundation/kernel_diagnostics.hpp>
#include <agent_kernel/memory/memory_identity.hpp>
#include <agent_kernel/memory/memory_objects.hpp>
#include <agent_kernel/planner/planner_identity.hpp>
#include <agent_kernel/planner/planning_request.hpp>
#include <agent_kernel/prompt/prompt_request.hpp>
#include <agent_kernel/prompt/prompt_section.hpp>
#include <agent_kernel/prompt/prompt_variable.hpp>

namespace ak::agent {
namespace {

std::string ModelActionKindName(ModelActionKind kind) {
    switch (kind) {
        case ModelActionKind::kToolInvoke:
            return "kToolInvoke";
        case ModelActionKind::kComplete:
            return "kComplete";
        case ModelActionKind::kInvalid:
            return "kInvalid";
    }
    return "kInvalid";
}

}  // namespace

// ------------------------------------------------------------
// Construction (TASK 6 Rev2 搂13 member order: roots before
// bindings/views)
// ------------------------------------------------------------
FirstWorkingAgentComposition::FirstWorkingAgentComposition(
    FirstWorkingAgentConfiguration configuration)
    : configuration_(std::move(configuration)),
      agent_(configuration_.agent_identity),
      planner_host_(configuration_.planner_identity,
                    configuration_.planner_config),
      prompt_host_(std::move(configuration_.prompt_definition)),
      tool_(std::move(configuration_.tool_id),
            std::move(configuration_.tool_config)),
      tool_binding_(tool_),
      context_(configuration_.context_identity),
      memory_(configuration_.memory_identity),
      model_boundary_(configuration_.model_boundary),
      tool_execution_boundary_(configuration_.tool_execution_boundary),
      max_cycles_(configuration_.max_cycles),
      objective_id_(),
      context_object_id_(ak::context::MakeContextObjectId(1)),
      memory_entry_id_() {}

// ------------------------------------------------------------
// Initialize() 鈥?TASK 6 Rev2 搂13 responsibilities, in order
// ------------------------------------------------------------
bool FirstWorkingAgentComposition::Initialize(
    const ExecutionObjective& objective) {
    if (initialized_) {
        agent_.Diagnostics().Add(
            ak::DiagnosticSeverity::kWarning, 100,
            "FirstWorkingAgentComposition::Initialize() called twice");
        return false;
    }

    // 2. Tool provider registration (RESOLVED mechanism 搂19.2):
    //    Register() -> Providers().Register(...) -> Activate().
    if (!tool_.Register().Succeeded()) {
        agent_.Diagnostics().Add(
            ak::DiagnosticSeverity::kError, 101,
            "Tool registration failed during FWA Initialize");
        return false;
    }
    for (auto& provider : configuration_.tool_providers) {
        const ak::tool::ProviderResult registered =
            tool_.Providers().Register(std::move(provider));
        if (registered.status != ak::tool::ToolResultStatus::kSuccess) {
            agent_.Diagnostics().Add(
                ak::DiagnosticSeverity::kError, 102,
                "Tool provider registration failed during FWA Initialize");
            return false;
        }
    }
    if (!tool_.Activate().Succeeded()) {
        agent_.Diagnostics().Add(
            ak::DiagnosticSeverity::kError, 103,
            "Tool activation failed during FWA Initialize");
        return false;
    }

    // 3. Bind the four acknowledge adapters (required gate of
    //    Agent::BeginCoordination()).
    agent_.Coordination().BindMemory(memory_adapter_);
    agent_.Coordination().BindContext(context_adapter_);
    agent_.Coordination().BindPlanner(planner_adapter_);
    agent_.Coordination().BindTool(tool_adapter_);

    // 4. Agent lifecycle: Uninitialized -> Ready.
    if (agent_.Initialize().Rejected()) {
        agent_.Diagnostics().Add(
            ak::DiagnosticSeverity::kError, 104,
            "Agent initialization failed during FWA Initialize");
        return false;
    }

    // 5. Accept the objective (Ready).
    if (!agent_.AcceptObjective(objective)) {
        agent_.Diagnostics().Add(
            ak::DiagnosticSeverity::kError, 105,
            "Objective acceptance failed during FWA Initialize");
        return false;
    }
    objective_id_ = objective.GetId();
    objective_description_ = objective.GetDescription();

    // 6. BeginCoordination: Ready -> Coordinating (all four
    //    contracts must be bound).
    if (agent_.BeginCoordination().Rejected()) {
        agent_.Diagnostics().Add(
            ak::DiagnosticSeverity::kError, 106,
            "Agent BeginCoordination failed during FWA Initialize");
        return false;
    }

    // 7. Context initialization (Context-owned per-object
    //    lifecycle: Create -> Initialize -> Activate).
    ak::context::ContextAgentContract& context_contract =
        context_.AgentContract();
    const ak::context::ContextResultValue<ak::context::ContextObjectId>
        created = context_contract.Creation().CreateObject(
            context_object_id_, "fwa-working-state", "initial context",
            ak::context::ContextMetadata{});
    if (!created.IsSuccess()) {
        agent_.Diagnostics().Add(
            ak::DiagnosticSeverity::kError, 107,
            "Context Object creation failed during FWA Initialize");
        return false;
    }
    if (!context_contract.Creation()
             .InitializeObject(context_object_id_)
             .IsSuccess()) {
        agent_.Diagnostics().Add(
            ak::DiagnosticSeverity::kError, 108,
            "Context Object initialization failed during FWA Initialize");
        return false;
    }
    if (!context_contract.Creation()
             .ActivateObject(context_object_id_)
             .IsSuccess()) {
        agent_.Diagnostics().Add(
            ak::DiagnosticSeverity::kError, 109,
            "Context Object activation failed during FWA Initialize");
        return false;
    }

    // 8. Memory lifecycle participation (Memory retains lifecycle
    //    ownership) + deterministic data-level participation.
    ak::memory::MemoryAgentContract& memory_contract =
        memory_.AgentContract();
    if (!memory_contract
             .RequestLifecycleParticipation(
                 ak::memory::MemoryLifecycleParticipation::kInitialize)
             .IsSuccess()) {
        agent_.Diagnostics().Add(
            ak::DiagnosticSeverity::kError, 110,
            "Memory lifecycle participation (kInitialize) failed");
        return false;
    }
    if (!memory_contract
             .RequestLifecycleParticipation(
                 ak::memory::MemoryLifecycleParticipation::kActivate)
             .IsSuccess()) {
        agent_.Diagnostics().Add(
            ak::DiagnosticSeverity::kError, 111,
            "Memory lifecycle participation (kActivate) failed");
        return false;
    }
    // Memory-owned operational readiness (composition owns the
    // Memory root; required for Memory service operations).
    if (!memory_.MarkReady().IsSuccess() ||
        !memory_.MarkAvailable().IsSuccess()) {
        agent_.Diagnostics().Add(
            ak::DiagnosticSeverity::kError, 112,
            "Memory operational readiness failed during FWA Initialize");
        return false;
    }
    // Deterministic seed entry so that data-level retrieval is
    // available (Memory -> Context/Prompt material flow).
    const ak::memory::MemoryResultValue<ak::memory::MemoryDomainId> domain =
        memory_contract.Services().CreateDomain(
            ak::memory::MakeMemoryDomainId(1), "fwa-domain",
            ak::memory::MemoryMetadata{});
    if (!domain.IsSuccess()) {
        agent_.Diagnostics().Add(
            ak::DiagnosticSeverity::kError, 113,
            "Memory domain creation failed during FWA Initialize");
        return false;
    }
    const ak::memory::MemoryResultValue<ak::memory::MemoryEntryId> retained =
        memory_contract.Services().Retain(
            ak::memory::MakeMemoryEntryId(1), domain.value,
            ak::memory::MemoryObject(
                ak::memory::MakeMemoryObjectId(1),
                "retained fact: fwa memory material",
                ak::memory::MemoryMetadata{}));
    if (!retained.IsSuccess()) {
        agent_.Diagnostics().Add(
            ak::DiagnosticSeverity::kError, 114,
            "Memory retention failed during FWA Initialize");
        return false;
    }
    memory_entry_id_ = retained.value;

    // 9. Planner lifecycle (Planner-owned).
    if (!planner_host_.Binding().Initialize().IsAccepted()) {
        agent_.Diagnostics().Add(
            ak::DiagnosticSeverity::kError, 115,
            "Planner lifecycle initialize failed during FWA Initialize");
        return false;
    }
    if (!planner_host_.Binding().Activate().IsAccepted()) {
        agent_.Diagnostics().Add(
            ak::DiagnosticSeverity::kError, 116,
            "Planner lifecycle activate failed during FWA Initialize");
        return false;
    }

    initialized_ = true;
    return true;
}

// ------------------------------------------------------------
// StepCycle() 鈥?one full planning -> prompt -> model -> action
// cycle (TASK 6 Rev2 搂22.1)
// ------------------------------------------------------------
FirstWorkingAgentComposition::InternalCycleResult
FirstWorkingAgentComposition::ExecuteToolPath(const ModelAction& action) {
    // 10. ModelAction interpretation: kToolInvoke.
    const ak::tool::CapabilityId* capability = action.Capability();
    if (capability == nullptr) {
        return FailCycle("fwa-cycle-failure",
                         "tool path entered without a capability");
    }
    const std::string& arguments = action.Arguments();

    // 11. Tool preparation (AC-008 discoverable, AC-009 kPrepared).
    const ak::tool::ToolCapabilityResult capability_result =
        tool_binding_.GetCapability(*capability);
    if (capability_result.status != ak::tool::ToolResultStatus::kSuccess) {
        return FailCycle("fwa-cycle-failure",
                         "tool-capability-not-found:" +
                             capability->Value());
    }
    ++invocation_counter_;
    const ak::tool::InvocationPreparationResult prepared =
        tool_binding_.PrepareInvocation(ak::tool::InvocationRequest{
            *capability,
            "fwa-invocation-" + std::to_string(invocation_counter_),
            arguments});
    if (prepared.status != ak::tool::InvocationPreparationStatus::kPrepared) {
        return FailCycle("fwa-cycle-failure",
                         "tool-preparation-failure:" +
                             std::to_string(
                                 static_cast<std::uint32_t>(prepared.status)));
    }

    // 12. Test-scoped execution seam (TASK 6 Rev2 搂20). Default
    //     (unconfigured) behavior is a deterministic failure 鈥?    //     the seam MUST NOT silently succeed (guardrail).
    if (!tool_execution_boundary_) {
        return FailCycle("fwa-cycle-failure",
                         "tool-execution-boundary-not-configured");
    }
    const std::string output =
        tool_execution_boundary_(*capability, arguments);
    if (output.empty()) {
        return FailCycle("fwa-cycle-failure",
                         "tool-executor-returned-empty-result");
    }

    // 13. Observation -> Context update (ContextAgentContract::
    //     Update(): Begin/Apply/Complete).
    ak::context::ContextUpdateService& update =
        context_.AgentContract().Update();
    if (!update.BeginUpdate(context_object_id_).IsSuccess()) {
        return FailCycle("fwa-cycle-failure",
                         "context-update-begin-failed");
    }
    if (!update.ApplyUpdate(context_object_id_, output,
                            ak::context::ContextMetadata{})
             .IsSuccess()) {
        return FailCycle("fwa-cycle-failure",
                         "context-update-apply-failed");
    }
    if (!update.CompleteUpdate(context_object_id_).IsSuccess()) {
        return FailCycle("fwa-cycle-failure",
                         "context-update-complete-failed");
    }

    // 14. Continue / complete decision: the tool step succeeded;
    //     the loop continues to the next cycle.
    return {CycleTermination::kContinue,
            CycleOutcome{false, "fwa-cycle-tool-invocation",
                         agent_.GetState(),
                         "planning:ok;prompt:ok;model:kToolInvoke;"
                         "tool:prepared;executor:ok;context:updated"}};
}

FirstWorkingAgentComposition::InternalCycleResult
FirstWorkingAgentComposition::CompleteCycle(
    const std::string& evidence_summary) {
    // 15. Legal lifecycle end: completion evaluation then end
    //     (OBS-02: default test ending is after EvaluateObjective,
    //     a legal non-Terminated point; only P1-IS002 transitions
    //     are used).
    const CompletionEvaluation evaluation = agent_.EvaluateObjective(
        objective_id_, ExecutionOutcomeSummary{true, evidence_summary});
    agent_.Diagnostics().Add(
        ak::DiagnosticSeverity::kInfo, 200,
        "FWA cycle completed; objective evaluated: " +
            std::string(evaluation.IsAchieved() ? "achieved" : "not-achieved"));
    return {CycleTermination::kCompleted,
            CycleOutcome{true, "fwa-cycle-completed", agent_.GetState(),
                         "planning:ok;prompt:ok;model:kComplete;"
                         "evaluation:" +
                             std::string(evaluation.IsAchieved()
                                             ? "achieved"
                                             : "not-achieved")}};
}

FirstWorkingAgentComposition::InternalCycleResult
FirstWorkingAgentComposition::FailCycle(const std::string& summary,
                                        const std::string& diagnostics) {
    agent_.Diagnostics().Add(ak::DiagnosticSeverity::kError, 201,
                             diagnostics);
    return {CycleTermination::kFailure,
            CycleOutcome{false, summary, agent_.GetState(), diagnostics}};
}

std::vector<ak::prompt::PromptInputBinding>
FirstWorkingAgentComposition::BuildPromptBindings(
    const std::string& context_content, const std::string& memory_content,
    const std::string& plan_payload,
    const std::string& tool_summary) const {
    std::vector<ak::prompt::PromptInputBinding> bindings;
    for (const ak::prompt::PromptVariable& variable :
         prompt_host_.Binding().Definition().Variables()) {
        std::string value;
        switch (variable.Category()) {
            case ak::prompt::PromptSectionKind::kUserInput:
                value = objective_description_;
                break;
            case ak::prompt::PromptSectionKind::kContextMaterial:
                value = context_content;
                break;
            case ak::prompt::PromptSectionKind::kMemoryMaterial:
                value = memory_content;
                break;
            case ak::prompt::PromptSectionKind::kPlanningMaterial:
                value = plan_payload;
                break;
            case ak::prompt::PromptSectionKind::kToolMaterial:
                value = tool_summary;
                break;
            default:
                // Static deterministic fallback for any other
                // declared material category.
                value = "Agent Kernel First Working Agent";
                break;
        }
        bindings.emplace_back(variable.Name(), std::move(value));
    }
    return bindings;
}

std::string FirstWorkingAgentComposition::BuildToolSummary() const {
    const ak::tool::ToolDiscoveryResult discovered = tool_binding_.Discover();
    if (discovered.status != ak::tool::ToolResultStatus::kSuccess ||
        discovered.capabilities.empty()) {
        return "no-tool-capabilities";
    }
    std::string summary;
    for (const ak::tool::ToolCapability& capability :
         discovered.capabilities) {
        if (!summary.empty()) {
            summary += ";";
        }
        summary += capability.id.Value();
    }
    return summary;
}

CycleOutcome FirstWorkingAgentComposition::StepCycle() {
    return StepCycleInternal().outcome;
}

FirstWorkingAgentComposition::InternalCycleResult
FirstWorkingAgentComposition::StepCycleInternal() {
    if (!initialized_) {
        return FailCycle("fwa-cycle-not-initialized",
                         "StepCycle() requires Initialize() first");
    }

    // 2. Context read (ContextAgentContract::Access()).
    const ak::context::ContextResultValue<ak::context::ContextObjectView>
        context_view =
            context_.AgentContract().Access().InspectObject(context_object_id_);
    if (!context_view.IsSuccess()) {
        return FailCycle("fwa-cycle-failure",
                         "context-read-failure:" +
                             std::string(context_view.message));
    }
    const std::string context_content = context_view.value.content;

    // 3. Memory information (optional data level; retrieval failure
    //    degrades to a deterministic missing-material marker).
    std::string memory_content = "no-memory-material";
    const ak::memory::MemoryResultValue<ak::memory::MemoryObject>
        memory_object = memory_.AgentContract().Services().Retrieve(
            memory_entry_id_);
    if (memory_object.IsSuccess()) {
        memory_content = memory_object.value.Content();
    }

    // 4-5. Planner invocation (AgentPlannerBinding).
    ++planning_request_counter_;
    ak::planner::PlanningRequest request;
    request.request_id = ak::planner::MakePlanningRequestId(
        planning_request_counter_);
    request.session_id = ak::planner::MakePlannerSessionId(
        ak::planner::kPrimaryPlannerSessionIdValue);
    request.goal = objective_description_;
    const ak::planner::PlanningAcceptance acceptance =
        planner_host_.Binding().Submit(request);
    if (!acceptance.IsAccepted()) {
        return FailCycle("fwa-cycle-failure",
                         "planner-failure:" +
                             std::string(acceptance.message));
    }
    const ak::planner::PlanningCompletionResult completion =
        planner_host_.Binding().CompletePlanningExchange(request.request_id);
    if (!completion.IsSuccess() || !completion.HasResult()) {
        return FailCycle("fwa-cycle-failure",
                         "planner-failure:" +
                             std::string(completion.message));
    }
    const std::string plan_payload =
        completion.result.artifact_view.payload;

    // 6. Prompt assembly (Agent-side translation of the planning
    //    snapshot into PromptInputBinding entries).
    const std::vector<ak::prompt::PromptInputBinding> bindings =
        BuildPromptBindings(context_content, memory_content, plan_payload,
                            BuildToolSummary());
    const ak::prompt::PromptAssemblyResult assembly =
        prompt_host_.Binding().Assemble(
            ak::prompt::PromptAssemblyRequest(bindings));

    // 7. PromptResult.
    if (!assembly.Succeeded() || !assembly.result.has_value()) {
        return FailCycle("fwa-cycle-failure",
                         "prompt-failure:" +
                             std::to_string(
                                 static_cast<std::uint32_t>(assembly.status)));
    }
    const ak::prompt::PromptResult& prompt_result = *assembly.result;

    // 8-9. Model boundary (composition-owned callable).
    const ModelAction action = model_boundary_(prompt_result);
    const std::string model_kind = ModelActionKindName(action.Kind());

    // 10. ModelAction interpretation.
    if (action.IsInvalid()) {
        const std::string reason = action.Reason();
        agent_.Diagnostics().Add(ak::DiagnosticSeverity::kError, 202, reason);
        return {CycleTermination::kInvalid,
                CycleOutcome{false, "fwa-cycle-invalid",
                             agent_.GetState(),
                             "model:" + model_kind + ";reason:" + reason}};
    }
    if (action.IsComplete()) {
        return CompleteCycle(objective_description_);
    }

    return ExecuteToolPath(action);
}

CycleOutcome FirstWorkingAgentComposition::Run() {
    if (!initialized_) {
        return FailCycle("fwa-cycle-not-initialized",
                         "Run() requires Initialize() first")
            .outcome;
    }
    if (!model_boundary_) {
        return FailCycle("fwa-cycle-failure",
                         "model-boundary-not-configured")
            .outcome;
    }
    for (std::size_t cycle = 0; cycle < max_cycles_; ++cycle) {
        const InternalCycleResult result = StepCycleInternal();
        if (result.termination == CycleTermination::kCompleted ||
            result.termination == CycleTermination::kInvalid ||
            result.termination == CycleTermination::kFailure) {
            return result.outcome;
        }
    }
    return {false, "fwa-cycle-max-cycles-exhausted", agent_.GetState(),
            "max-cycles:" + std::to_string(max_cycles_)};
}

}  // namespace ak::agent
