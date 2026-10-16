// ============================================================
// model_result_test.cpp - P1-IS008 Rev1.0 Chapters 8, 14, 19.2
// ============================================================
// ModelResult tests: Success/InvalidResult/Failure, payload,
// diagnostic, validity semantics, value semantics (copy/move),
// lifetime after return, error categories, and the distinction
// from ak::agent::ModelAction.
// ============================================================

#include <agent_kernel/model/model_result.hpp>

#include <gtest/gtest.h>

#include <agent_kernel/fwa/model_action.hpp>
#include <agent_kernel/tool/tool_identity.hpp>

#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>

namespace ak::model {
namespace {

// Lifetime-after-return evidence: a ModelResult produced by a
// function remains valid and owned by the caller copy.
ModelResult ProduceResult() {
    return ModelResult::Success("produced payload");
}

TEST(ModelResult, SuccessCarriesPayload) {
    const ModelResult result = ModelResult::Success("plan the next step");
    EXPECT_TRUE(result.IsSuccess());
    EXPECT_TRUE(result.Valid());
    EXPECT_EQ(result.Status(), ModelStatus::kSuccess);
    EXPECT_EQ(result.ErrorCategory(), ModelErrorCategory::kNone);
    ASSERT_TRUE(result.Payload().has_value());
    EXPECT_EQ(result.Payload().value(), "plan the next step");
    EXPECT_TRUE(result.Diagnostic().empty());
}

TEST(ModelResult, SuccessRejectsEmptyPayload) {
    // An empty model output is not a valid success (Chapter 8).
    EXPECT_THROW(ModelResult::Success(""), std::invalid_argument);
}

TEST(ModelResult, InvalidResultIsRepresented) {
    const ModelResult result =
        ModelResult::InvalidResult("provider output is not interpretable");
    EXPECT_TRUE(result.IsInvalidResult());
    EXPECT_FALSE(result.Valid());
    EXPECT_EQ(result.Status(), ModelStatus::kInvalidResult);
    EXPECT_EQ(result.ErrorCategory(), ModelErrorCategory::kInvalidResult);
    EXPECT_FALSE(result.Payload().has_value());
    EXPECT_EQ(result.Diagnostic(), "provider output is not interpretable");
}

TEST(ModelResult, InvalidResultRejectsEmptyDiagnostic) {
    EXPECT_THROW(ModelResult::InvalidResult(""), std::invalid_argument);
}

TEST(ModelResult, FailureIsRepresented) {
    const ModelResult result = ModelResult::Failure("provider transport error");
    EXPECT_TRUE(result.IsFailure());
    EXPECT_FALSE(result.Valid());
    EXPECT_EQ(result.Status(), ModelStatus::kFailure);
    EXPECT_EQ(result.ErrorCategory(), ModelErrorCategory::kModelFailure);
    EXPECT_FALSE(result.Payload().has_value());
    EXPECT_EQ(result.Diagnostic(), "provider transport error");
}

TEST(ModelResult, FailureCanClassifyInvalidInput) {
    const ModelResult result =
        ModelResult::Failure("model-facing input is invalid",
                             ModelErrorCategory::kInvalidInput);
    EXPECT_TRUE(result.IsFailure());
    EXPECT_EQ(result.ErrorCategory(), ModelErrorCategory::kInvalidInput);
}

TEST(ModelResult, FailureRejectsEmptyDiagnostic) {
    EXPECT_THROW(ModelResult::Failure(""), std::invalid_argument);
}

TEST(ModelResult, ValueSemanticsCopyAndMove) {
    const ModelResult original = ModelResult::Success("copyable");
    const ModelResult copy = original;
    EXPECT_TRUE(copy.IsSuccess());
    EXPECT_EQ(copy.Payload().value(), "copyable");

    ModelResult source = ModelResult::Failure("movable");
    const ModelResult moved = std::move(source);
    EXPECT_TRUE(moved.IsFailure());
    EXPECT_EQ(moved.Diagnostic(), "movable");
}

TEST(ModelResult, LifetimeAfterReturn) {
    const ModelResult result = ProduceResult();
    EXPECT_TRUE(result.Valid());
    EXPECT_EQ(result.Payload().value(), "produced payload");
    // The returned value remains valid for synchronous Agent
    // interpretation (Chapter 8); no shared/background lifetime.
    const std::string payload_copy = result.Payload().value();
    EXPECT_EQ(payload_copy, "produced payload");
}

TEST(ModelResult, DistinctFromModelAction) {
    // Chapter 8: ModelResult is NOT ModelAction. ModelResult is
    // Model-owned inference output; ModelAction is the Agent-owned
    // actionable interpretation boundary value (Chapter 9).
    static_assert(!std::is_same_v<ak::model::ModelResult,
                                  ak::agent::ModelAction>);
    // A ModelResult payload is not an action: it carries no
    // capability and no action kind; interpretation is Agent-owned.
    const ModelResult result =
        ModelResult::Success("tool:capability:arguments");
    EXPECT_TRUE(result.IsSuccess());
    EXPECT_FALSE(result.Payload().value().empty());
}

}  // namespace
}  // namespace ak::model
