// ============================================================
// agent_model_binding_test.cpp - P1-IS008 Rev1.0 Chapter 15
// ============================================================
// AgentModelBinding is the sole Agent-facing Model coordination
// boundary: a NON-OWNING view that forwards identity, state,
// lifecycle, and inference to the Model root and returns the
// Model root's own ModelResult (never interpreted).
// ============================================================

#include <agent_kernel/agent_model/agent_model_binding.hpp>

#include <gtest/gtest.h>

#include "../model/deterministic_model.hpp"

#include <string>
#include <type_traits>

namespace ak {
namespace {

using ak::model::ModelErrorCategory;
using ak::model::ModelId;
using ak::model::ModelInput;
using ak::model::ModelLifecycleState;
using ak::model::test::DeterministicModel;
using ak::model::test::DeterministicModelMode;

TEST(AgentModelBinding, ForwardsIdentityAndState) {
    DeterministicModel model(ModelId("bound-model"),
                             DeterministicModelMode::kFixedSuccess, "ok");
    const agent::AgentModelBinding binding(model);
    EXPECT_EQ(binding.Id(), ModelId("bound-model"));
    EXPECT_EQ(binding.State(), ModelLifecycleState::kUninitialized);
}

TEST(AgentModelBinding, ForwardsLifecycle) {
    DeterministicModel model(ModelId("bound-model"),
                             DeterministicModelMode::kFixedSuccess, "ok");
    agent::AgentModelBinding binding(model);
    EXPECT_TRUE(binding.Initialize().Accepted());
    EXPECT_EQ(binding.State(), ModelLifecycleState::kReady);
    EXPECT_TRUE(binding.Shutdown().Accepted());
    EXPECT_EQ(binding.State(), ModelLifecycleState::kShutdown);
}

TEST(AgentModelBinding, ForwardsInferenceResult) {
    DeterministicModel model(ModelId("bound-model"),
                             DeterministicModelMode::kEcho);
    agent::AgentModelBinding binding(model);
    EXPECT_TRUE(binding.Initialize().Accepted());
    const model::ModelResult result =
        binding.Infer(ModelInput("agent-facing input"));
    EXPECT_TRUE(result.IsSuccess());
    ASSERT_TRUE(result.Payload().has_value());
    EXPECT_EQ(result.Payload().value(), "echo:agent-facing input");
}

TEST(AgentModelBinding, ReturnsModelOwnedResultUninterpreted) {
    DeterministicModel model(ModelId("bound-model"),
                             DeterministicModelMode::kInvalidResult, "p",
                             "provider output is not interpretable");
    agent::AgentModelBinding binding(model);
    EXPECT_TRUE(binding.Initialize().Accepted());
    const model::ModelResult result =
        binding.Infer(ModelInput("agent-facing input"));
    // The binding does not interpret or rewrite the Model-owned
    // result (Chapters 8, 15).
    EXPECT_TRUE(result.IsInvalidResult());
    EXPECT_EQ(result.ErrorCategory(), ModelErrorCategory::kInvalidResult);
    EXPECT_EQ(result.Diagnostic(), "provider output is not interpretable");
}

TEST(AgentModelBinding, BindingIsNonOwningAndNonCopyable) {
    static_assert(!std::is_copy_constructible_v<agent::AgentModelBinding>);
    static_assert(!std::is_move_constructible_v<agent::AgentModelBinding>);
}

}  // namespace
}  // namespace ak
