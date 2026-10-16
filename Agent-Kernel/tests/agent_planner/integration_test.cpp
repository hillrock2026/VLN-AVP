// ============================================================
// integration_test.cpp - P1-IS005 Agent integration tests
// ============================================================
// Chapter 20.5: uses the REAL production types - AgentPlannerHost,
// AgentPlannerBinding, Planner, ImmediatePlanningEngine. No
// Agent-role double is used for the planning path.
//
// Also verifies the unchanged Phase 1 generic surface:
// ak::agent::IPlannerContract and ak::agent::AgentCoordinationService
// (PLN-049; Chapter 14.4).
// ============================================================

#include <agent_kernel/agent/agent.hpp>
#include <agent_kernel/agent/coordination/agent_coordination_service.hpp>
#include <agent_kernel/agent/coordination/i_planner_contract.hpp>
#include <agent_kernel/agent_planner/agent_planner_host.hpp>
#include <agent_kernel/planner/planner.hpp>
#include <agent_kernel/planner/planning_request.hpp>

#include <gtest/gtest.h>

#include <string>
#include <string_view>
#include <type_traits>
#include <utility>

namespace ak::agent {
namespace pl = ak::planner;

namespace {

class TestPlannerContract final : public IPlannerContract {
public:
    std::string_view ContractName() const noexcept override { return "Planner"; }

    CoordinationAcknowledgement AcknowledgeCoordination() override {
        return {true, "acknowledged"};
    }
};

// Negative surface: the Phase 1 generic IPlannerContract SHALL
// NOT carry planning request/result semantics (Chapter 14.4).
template <typename T, typename = void>
struct HasSubmitPlanningRequest : std::false_type {};
template <typename T>
struct HasSubmitPlanningRequest<
    T, std::void_t<decltype(std::declval<T&>().Submit(
           std::declval<const pl::PlanningRequest&>()))>> : std::true_type {};

template <typename T, typename = void>
struct HasCompletePlanningExchange : std::false_type {};
template <typename T>
struct HasCompletePlanningExchange<
    T, std::void_t<decltype(std::declval<T&>().CompletePlanningExchange(
           std::declval<const pl::PlanningRequestId&>()))>> : std::true_type {};

TEST(PlannerIntegration, RealCompositionOwnsRealPlanner) {
    const pl::PlannerIdentity identity = pl::MakePlannerIdentity(300);
    AgentPlannerHost host(identity);

    EXPECT_EQ(host.GetPlannerIdentity(), identity);
    EXPECT_EQ(host.Planner().GetIdentity(), identity);
    EXPECT_EQ(&host.Binding().Capability(), &host.Planner().AgentContract());
    EXPECT_EQ(&host.Binding().Lifecycle(), &host.Planner().LifecycleContract());
}

TEST(PlannerIntegration, RealEndToEndPlanningPath) {
    AgentPlannerHost host(pl::MakePlannerIdentity(301));
    auto& binding = host.Binding();

    // Lifecycle participation (Agent -> Host -> Binding ->
    // Lifecycle contract -> Planner).
    ASSERT_TRUE(binding.Initialize().IsAccepted());
    ASSERT_TRUE(binding.Activate().IsAccepted());
    EXPECT_EQ(binding.GetOperationalState(), pl::PlannerOperationalState::kReady);

    // Planning capability (Agent -> Host -> Binding -> Capability
    // contract -> Planner).
    pl::PlanningRequest request;
    request.request_id = pl::MakePlanningRequestId(7);
    request.session_id = pl::MakePlannerSessionId(pl::kPrimaryPlannerSessionIdValue);
    request.goal = "integration-goal";

    const auto acceptance = binding.Submit(request);
    ASSERT_TRUE(acceptance.IsAccepted());
    EXPECT_EQ(binding.GetOperationalState(), pl::PlannerOperationalState::kPlanning);

    const auto completion = binding.CompletePlanningExchange(request.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    ASSERT_TRUE(completion.HasResult());
    EXPECT_EQ(completion.result.request_id, request.request_id);
    EXPECT_TRUE(completion.result.result_id.IsValid());
    EXPECT_TRUE(completion.result.artifact_view.artifact_id.IsValid());
    EXPECT_EQ(completion.result.artifact_view.payload, "integration-goal");
    EXPECT_EQ(completion.result.artifact_view.session_id, request.session_id);

    // Drain: the REAL planner committed Planning -> Ready.
    EXPECT_EQ(binding.GetOperationalState(), pl::PlannerOperationalState::kReady);
    EXPECT_EQ(host.Planner().GetLifecycleState(), pl::PlannerLifecycleState::kReady);
}

TEST(PlannerIntegration, RealInvocationPathIsNotATestHelper) {
    AgentPlannerHost host(pl::MakePlannerIdentity(302));
    auto& binding = host.Binding();

    ASSERT_TRUE(binding.Initialize().IsAccepted());
    ASSERT_TRUE(binding.Activate().IsAccepted());

    pl::PlanningRequest request;
    request.request_id = pl::MakePlanningRequestId(11);
    request.session_id = pl::MakePlannerSessionId(pl::kPrimaryPlannerSessionIdValue);
    request.goal = "real-path";

    const auto acceptance = binding.Submit(request);
    ASSERT_TRUE(acceptance.IsAccepted());
    const auto completion = binding.CompletePlanningExchange(request.request_id);
    ASSERT_TRUE(completion.IsSuccess());

    // The request/result correlation proves the result was
    // produced by the REAL Planner service of the host.
    EXPECT_EQ(completion.result.request_id, pl::MakePlanningRequestId(11));
    EXPECT_TRUE(completion.result.result_id.IsValid());

    // Refusal gate after termination (Chapter 15.3): no Planner
    // service is invoked after Terminated.
    ASSERT_TRUE(binding.Terminate().IsAccepted());
    EXPECT_EQ(binding.GetOperationalState(), pl::PlannerOperationalState::kTerminated);

    pl::PlanningRequest late;
    late.request_id = pl::MakePlanningRequestId(12);
    late.session_id = pl::MakePlannerSessionId(pl::kPrimaryPlannerSessionIdValue);
    late.goal = "late";
    EXPECT_EQ(binding.Submit(late).status, pl::PlanningAcceptanceStatus::kUnavailable);
    EXPECT_EQ(binding.CompletePlanningExchange(late.request_id).status,
              pl::PlanningCompletionStatus::kRejectedTerminated);
    EXPECT_EQ(host.Planner().OpenExchangeCount(), 0);
}

TEST(PlannerIntegration, Phase1GenericSurfaceRemainsUnchanged) {
    // IPlannerContract still exposes only the Phase 1 generic
    // coordination surface.
    TestPlannerContract contract;
    EXPECT_EQ(contract.ContractName(), "Planner");
    const auto acknowledgement = contract.AcknowledgeCoordination();
    EXPECT_TRUE(acknowledgement.accepted);

    // AgentCoordinationService still binds the generic contract
    // for coordination acknowledgments.
    AgentCoordinationService coordination;
    EXPECT_TRUE(coordination.BindPlanner(contract));
    EXPECT_TRUE(coordination.IsBound(SubsystemId::kPlanner));
    const auto result = coordination.CoordinatePlanner();
    EXPECT_TRUE(result.accepted);
    EXPECT_EQ(coordination.CoordinatedSubsystemCount(), 1);

    // IPlannerContract SHALL NOT become a competing planning API.
    static_assert(!HasSubmitPlanningRequest<IPlannerContract>::value,
                  "IPlannerContract must not carry PlanningRequest semantics");
    static_assert(!HasCompletePlanningExchange<IPlannerContract>::value,
                  "IPlannerContract must not carry PlanningResult semantics");
}

TEST(PlannerIntegration, HostBuildsAndRunsWithoutRuntimeTarget) {
    // This executable links agent_kernel_agent_planner,
    // agent_kernel_planner, and agent_kernel_agent together with
    // no Runtime target; a full round-trip proves Phase 3
    // independence (PLN-002/068).
    AgentPlannerHost host(pl::MakePlannerIdentity(303));
    auto& binding = host.Binding();

    ASSERT_TRUE(binding.Initialize().IsAccepted());
    ASSERT_TRUE(binding.Activate().IsAccepted());

    pl::PlanningRequest request;
    request.request_id = pl::MakePlanningRequestId(21);
    request.session_id = pl::MakePlannerSessionId(pl::kPrimaryPlannerSessionIdValue);
    request.goal = "no-runtime";

    const auto acceptance = binding.Submit(request);
    ASSERT_TRUE(acceptance.IsAccepted());
    const auto completion = binding.CompletePlanningExchange(request.request_id);
    ASSERT_TRUE(completion.IsSuccess());
    EXPECT_EQ(completion.result.artifact_view.payload, "no-runtime");
}

}  // namespace
}  // namespace ak::agent
