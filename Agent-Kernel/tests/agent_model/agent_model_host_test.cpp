// ============================================================
// agent_model_host_test.cpp - P1-IS008 Rev1.0 Chapters 7, 15
// ============================================================
// AgentModelHost is the production composition root: it owns the
// injected Model root and exposes only the Agent-facing Binding.
// Construction order is normative (root before binding view).
// ============================================================

#include <agent_kernel/agent_model/agent_model_host.hpp>

#include <gtest/gtest.h>

#include "../model/deterministic_model.hpp"

#include <memory>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>

namespace ak {
namespace {

using ak::model::ModelId;
using ak::model::ModelInput;
using ak::model::ModelLifecycleState;
using ak::model::test::DeterministicModel;
using ak::model::test::DeterministicModelMode;

TEST(AgentModelHost, OwnsInjectedModelRoot) {
    auto model = std::make_unique<DeterministicModel>(
        ModelId("host-model"), DeterministicModelMode::kFixedSuccess, "host-ok");
    agent::AgentModelHost host(std::move(model));

    EXPECT_EQ(host.Binding().Id(), ModelId("host-model"));
    EXPECT_EQ(host.Binding().State(), ModelLifecycleState::kUninitialized);
    EXPECT_TRUE(host.Binding().Initialize().Accepted());
    EXPECT_EQ(host.Binding().State(), ModelLifecycleState::kReady);

    const model::ModelResult result =
        host.Binding().Infer(ModelInput("host input"));
    EXPECT_TRUE(result.IsSuccess());
    ASSERT_TRUE(result.Payload().has_value());
    EXPECT_EQ(result.Payload().value(), "host-ok");
}

TEST(AgentModelHost, RejectsNullModel) {
    // A null Model is a deterministic construction failure; the
    // Agent must always have a configured Model boundary.
    EXPECT_THROW(agent::AgentModelHost(nullptr), std::invalid_argument);
}

TEST(AgentModelHost, ShutdownReleasesOnlyModelOwnedResources) {
    auto model = std::make_unique<DeterministicModel>(
        ModelId("host-model"), DeterministicModelMode::kFixedSuccess, "ok");
    agent::AgentModelHost host(std::move(model));
    EXPECT_TRUE(host.Binding().Initialize().Accepted());
    EXPECT_TRUE(host.Binding().Shutdown().Accepted());
    EXPECT_EQ(host.Binding().State(), ModelLifecycleState::kShutdown);
}

TEST(AgentModelHost, HostIsNonCopyableAndNonMovable) {
    static_assert(!std::is_copy_constructible_v<agent::AgentModelHost>);
    static_assert(!std::is_move_constructible_v<agent::AgentModelHost>);
}

}  // namespace
}  // namespace ak
