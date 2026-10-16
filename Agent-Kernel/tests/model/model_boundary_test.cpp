// ============================================================
// model_boundary_test.cpp - P1-IS008 Rev1.0 Chapters 16, 19.4
// ============================================================
// Behavioral boundary evidence for the Model implementation.
// Static include/link boundary verification is performed by the
// registered CTest check_model_boundaries.cmake (no Runtime, no
// Tool, no Memory/Context/Planner/Agent/Prompt include, no
// provider SDK, foundation-only link). This file adds
// compile-time and behavioral boundary assertions.
// ============================================================

#include <agent_kernel/model/model.hpp>
#include <agent_kernel/model/model_input.hpp>
#include <agent_kernel/model/model_result.hpp>

#include <gtest/gtest.h>

#include "deterministic_model.hpp"

#include <type_traits>
#include <utility>

namespace ak::model {
namespace {

// The Model boundary is an abstraction (Agent -> Model
// abstraction, never a concrete provider SDK, Chapter 11).
static_assert(std::is_abstract_v<Model>);
static_assert(!std::is_abstract_v<test::DeterministicModel>);

// Model boundary values use value semantics for synchronous
// Agent interpretation (Chapter 8).
static_assert(std::is_copy_constructible_v<ModelInput>);
static_assert(std::is_move_constructible_v<ModelInput>);
static_assert(std::is_copy_constructible_v<ModelResult>);
static_assert(std::is_move_constructible_v<ModelResult>);

TEST(ModelBoundary, ModelIsDistinctFromAgent) {
    // IS-AC-001: the Model contract lives in ak::model and is a
    // separate implementation boundary from the Agent.
    ModelId id("boundary-model");
    test::DeterministicModel model(
        std::move(id), test::DeterministicModelMode::kFixedSuccess, "ok");
    EXPECT_EQ(model.Id(), ModelId("boundary-model"));
}

TEST(ModelBoundary, InferenceDoesNotExecuteTool) {
    // FD-001/FD-002: inference produces a ModelResult payload; it
    // does not execute, prepare, or own a Tool. The payload is
    // inert until Agent interpretation (Chapter 8).
    test::DeterministicModel model(
        ModelId("boundary-model"),
        test::DeterministicModelMode::kFixedSuccess, "tool:cap:args");
    EXPECT_TRUE(model.Initialize().Accepted());
    const ModelResult result = model.Infer(ModelInput("input"));
    ASSERT_TRUE(result.IsSuccess());
    // The payload is a plain string; no capability/action object
    // was created or executed by the Model boundary.
    EXPECT_EQ(result.Payload().value(), "tool:cap:args");
    EXPECT_EQ(model.inference_count(), 1u);
}

TEST(ModelBoundary, InferenceRequiresNoRuntime) {
    // FD-003/FD-004: constructing, initializing, and running the
    // Model requires no Runtime service, Scheduler, or Executor.
    test::DeterministicModel model(
        ModelId("runtime-free"), test::DeterministicModelMode::kEcho);
    EXPECT_TRUE(model.Initialize().Accepted());
    const ModelResult result = model.Infer(ModelInput("no runtime"));
    EXPECT_TRUE(result.IsSuccess());
    EXPECT_EQ(result.Payload().value(), "echo:no runtime");
}

TEST(ModelBoundary, ModelOwnsNeitherMemoryNorContext) {
    // FD-007/FD-008: the Model consumes only its model-facing
    // input; it holds no Memory/Context object.
    test::DeterministicModel model(
        ModelId("memory-free"), test::DeterministicModelMode::kEcho);
    EXPECT_TRUE(model.Initialize().Accepted());
    const ModelInput input("prompt-assembled content");
    const ModelResult result = model.Infer(input);
    EXPECT_TRUE(result.IsSuccess());
    EXPECT_EQ(model.last_input_content(), "prompt-assembled content");
}

TEST(ModelBoundary, ModelDoesNotAssemblePrompt) {
    // FD-010: the Model never assembles its own input; it only
    // consumes the model-facing input handed to it.
    test::DeterministicModel model(
        ModelId("prompt-free"), test::DeterministicModelMode::kEcho);
    EXPECT_TRUE(model.Initialize().Accepted());
    const ModelResult result = model.Infer(ModelInput("provided input"));
    EXPECT_EQ(result.Payload().value(), "echo:provided input");
}

}  // namespace
}  // namespace ak::model
