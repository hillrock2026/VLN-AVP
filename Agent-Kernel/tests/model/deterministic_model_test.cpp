// ============================================================
// deterministic_model_test.cpp - P1-IS008 Rev1.0 Chapters 10,
// 13, 19.1, 19.5
// ============================================================
// Deterministic Model tests through the ak::model::Model
// contract: construction/identity, lifecycle, inference
// success/failure/invalid-result, error semantics, determinism
// (same input -> same output, repeated runs), and the absence
// of Tool/Runtime involvement.
// ============================================================

#include <agent_kernel/model/model.hpp>
#include <agent_kernel/model/model_input.hpp>
#include <agent_kernel/model/model_result.hpp>

#include <gtest/gtest.h>

#include "deterministic_model.hpp"

#include <string>
#include <utility>

namespace ak::model {
namespace {

using test::DeterministicModel;
using test::DeterministicModelMode;

const ModelInput kInput("assemble the next step");

DeterministicModel MakeModel(DeterministicModelMode mode,
                             std::string payload = "deterministic-payload",
                             std::string diagnostic = "deterministic-failure") {
    return DeterministicModel(ModelId("deterministic-model"), mode,
                              std::move(payload), std::move(diagnostic));
}

TEST(DeterministicModel, ConstructionAndIdentity) {
    const DeterministicModel model =
        MakeModel(DeterministicModelMode::kFixedSuccess);
    EXPECT_EQ(model.Id(), ModelId("deterministic-model"));
    EXPECT_EQ(model.State(), ModelLifecycleState::kUninitialized);
}

TEST(DeterministicModel, Initialization) {
    DeterministicModel model = MakeModel(DeterministicModelMode::kFixedSuccess);
    const ak::TransitionResult init = model.Initialize();
    EXPECT_TRUE(init.Accepted());
    EXPECT_EQ(model.State(), ModelLifecycleState::kReady);
}

TEST(DeterministicModel, RejectsDoubleInitialization) {
    DeterministicModel model = MakeModel(DeterministicModelMode::kFixedSuccess);
    EXPECT_TRUE(model.Initialize().Accepted());
    const ak::TransitionResult again = model.Initialize();
    EXPECT_TRUE(again.Rejected());
    EXPECT_EQ(model.State(), ModelLifecycleState::kReady);
}

TEST(DeterministicModel, ShutdownReleasesModelOnly) {
    DeterministicModel model = MakeModel(DeterministicModelMode::kFixedSuccess);
    EXPECT_TRUE(model.Initialize().Accepted());
    EXPECT_TRUE(model.Shutdown().Accepted());
    EXPECT_EQ(model.State(), ModelLifecycleState::kShutdown);
    EXPECT_TRUE(model.Shutdown().Rejected());
}

TEST(DeterministicModel, InitializeReportsUnavailableProvider) {
    DeterministicModel model =
        MakeModel(DeterministicModelMode::kUnavailableOnInitialize);
    const ak::TransitionResult init = model.Initialize();
    EXPECT_TRUE(init.Accepted());
    EXPECT_EQ(model.State(), ModelLifecycleState::kUnavailable);
}

TEST(DeterministicModel, InferenceBeforeInitializationFails) {
    DeterministicModel model = MakeModel(DeterministicModelMode::kFixedSuccess);
    const ModelResult result = model.Infer(kInput);
    EXPECT_TRUE(result.IsFailure());
    EXPECT_FALSE(result.Valid());
    EXPECT_EQ(result.ErrorCategory(), ModelErrorCategory::kModelFailure);
}

TEST(DeterministicModel, InferenceWhileShutdownFails) {
    DeterministicModel model = MakeModel(DeterministicModelMode::kFixedSuccess);
    EXPECT_TRUE(model.Initialize().Accepted());
    EXPECT_TRUE(model.Shutdown().Accepted());
    const ModelResult result = model.Infer(kInput);
    EXPECT_TRUE(result.IsFailure());
    EXPECT_EQ(result.ErrorCategory(), ModelErrorCategory::kModelFailure);
}

TEST(DeterministicModel, InferenceWhileUnavailableFails) {
    DeterministicModel model =
        MakeModel(DeterministicModelMode::kUnavailableOnInitialize);
    EXPECT_TRUE(model.Initialize().Accepted());
    const ModelResult result = model.Infer(kInput);
    EXPECT_TRUE(result.IsFailure());
    EXPECT_EQ(result.ErrorCategory(), ModelErrorCategory::kModelFailure);
}

TEST(DeterministicModel, FixedSuccessInference) {
    DeterministicModel model =
        MakeModel(DeterministicModelMode::kFixedSuccess, "fixed-response");
    EXPECT_TRUE(model.Initialize().Accepted());
    const ModelResult result = model.Infer(kInput);
    EXPECT_TRUE(result.IsSuccess());
    EXPECT_TRUE(result.Valid());
    ASSERT_TRUE(result.Payload().has_value());
    EXPECT_EQ(result.Payload().value(), "fixed-response");
}

TEST(DeterministicModel, InvalidResultScenario) {
    DeterministicModel model =
        MakeModel(DeterministicModelMode::kInvalidResult, "payload",
                  "provider output is not interpretable");
    EXPECT_TRUE(model.Initialize().Accepted());
    const ModelResult result = model.Infer(kInput);
    EXPECT_TRUE(result.IsInvalidResult());
    EXPECT_FALSE(result.Valid());
    EXPECT_FALSE(result.Payload().has_value());
    EXPECT_EQ(result.Diagnostic(), "provider output is not interpretable");
}

TEST(DeterministicModel, ModelFailureScenario) {
    DeterministicModel model =
        MakeModel(DeterministicModelMode::kFailure, "payload",
                  "provider transport error");
    EXPECT_TRUE(model.Initialize().Accepted());
    const ModelResult result = model.Infer(kInput);
    EXPECT_TRUE(result.IsFailure());
    EXPECT_FALSE(result.Valid());
    EXPECT_EQ(result.ErrorCategory(), ModelErrorCategory::kModelFailure);
    EXPECT_EQ(result.Diagnostic(), "provider transport error");
}

TEST(DeterministicModel, InvalidInputCategoryScenario) {
    DeterministicModel model =
        MakeModel(DeterministicModelMode::kInvalidInput, "payload",
                  "model-facing input is invalid");
    EXPECT_TRUE(model.Initialize().Accepted());
    const ModelResult result = model.Infer(kInput);
    EXPECT_TRUE(result.IsFailure());
    EXPECT_EQ(result.ErrorCategory(), ModelErrorCategory::kInvalidInput);
    EXPECT_EQ(result.Diagnostic(), "model-facing input is invalid");
}

TEST(DeterministicModel, FailureReturnsToReusableReadyState) {
    // Chapter 10: failure returns to a reusable state when
    // supported; a failed inference does not transition the
    // Model state machine.
    DeterministicModel model =
        MakeModel(DeterministicModelMode::kFailure, "payload", "transient");
    EXPECT_TRUE(model.Initialize().Accepted());
    EXPECT_TRUE(model.Infer(kInput).IsFailure());
    EXPECT_EQ(model.State(), ModelLifecycleState::kReady);
    EXPECT_TRUE(model.Infer(kInput).IsFailure());
}

TEST(DeterministicModel, DeterministicSameInputSameOutput) {
    DeterministicModel model =
        MakeModel(DeterministicModelMode::kEcho);
    EXPECT_TRUE(model.Initialize().Accepted());
    const ModelResult first = model.Infer(kInput);
    const ModelResult second = model.Infer(kInput);
    ASSERT_TRUE(first.IsSuccess());
    ASSERT_TRUE(second.IsSuccess());
    EXPECT_EQ(first.Payload().value(), second.Payload().value());
    EXPECT_EQ(first.Payload().value(), "echo:assemble the next step");
}

TEST(DeterministicModel, DeterministicAcrossRepeatedRuns) {
    // Chapter 19.5: repeated identical inputs produce identical
    // results; no network, credentials, provider availability,
    // GPU, ROS2, MuJoCo, or G1 is involved.
    DeterministicModel model =
        MakeModel(DeterministicModelMode::kEcho);
    EXPECT_TRUE(model.Initialize().Accepted());
    const std::string run_a = model.Infer(kInput).Payload().value();
    const std::string run_b = model.Infer(kInput).Payload().value();
    const std::string run_c = model.Infer(kInput).Payload().value();
    EXPECT_EQ(run_a, run_b);
    EXPECT_EQ(run_b, run_c);
}

TEST(DeterministicModel, ObservesReceivedInput) {
    DeterministicModel model =
        MakeModel(DeterministicModelMode::kEcho);
    EXPECT_TRUE(model.Initialize().Accepted());
    EXPECT_TRUE(model.Infer(kInput).IsSuccess());
    EXPECT_EQ(model.last_input_content(), "assemble the next step");
    EXPECT_EQ(model.inference_count(), 1u);
}

}  // namespace
}  // namespace ak::model
