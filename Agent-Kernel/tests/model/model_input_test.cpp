// ============================================================
// model_input_test.cpp - P1-IS008 Rev1.0 Chapters 7, 12, 14
// ============================================================
// ModelInput tests: immutable model-facing input, valid-input
// acceptance, InvalidInput construction rejection, and value
// semantics (copy/move).
// ============================================================

#include <agent_kernel/model/model_input.hpp>

#include <gtest/gtest.h>

#include <stdexcept>
#include <string>
#include <utility>

namespace ak::model {
namespace {

TEST(ModelInput, AcceptsValidContent) {
    const ModelInput input("assemble the next step");
    EXPECT_EQ(input.Content(), "assemble the next step");
}

TEST(ModelInput, RejectsEmptyContent) {
    // InvalidInput category (Chapter 14): malformed model-facing
    // input is rejected deterministically at construction.
    EXPECT_THROW(ModelInput(""), std::invalid_argument);
}

TEST(ModelInput, RejectsWhitespaceOnlyContent) {
    EXPECT_THROW(ModelInput("   "), std::invalid_argument);
    EXPECT_THROW(ModelInput("\r\n\t"), std::invalid_argument);
}

TEST(ModelInput, ImmutableAfterConstruction) {
    const ModelInput input("fixed content");
    // Only a const accessor exists; no mutation surface.
    EXPECT_EQ(input.Content(), "fixed content");
}

TEST(ModelInput, CopySemantics) {
    const ModelInput input("copy me");
    const ModelInput copy = input;
    EXPECT_EQ(copy.Content(), input.Content());
}

TEST(ModelInput, MoveSemantics) {
    ModelInput source("move me");
    const ModelInput moved = std::move(source);
    EXPECT_EQ(moved.Content(), "move me");
}

}  // namespace
}  // namespace ak::model
