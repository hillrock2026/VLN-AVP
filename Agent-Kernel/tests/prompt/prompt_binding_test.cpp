// ============================================================
// prompt_binding_test.cpp - P1-IS007 Rev1.1 Chapter 33
// ============================================================
// Input binding tests: value-based binding (PRM-012),
// boundary-value representation with no source-object
// ownership (PRM-037), immutability (Chapter 17), and
// malformed-binding rejection (Chapter 25.1).
// ============================================================

#include <agent_kernel/prompt/prompt_binding.hpp>

#include <gtest/gtest.h>

#include <stdexcept>
#include <string>

namespace ak::prompt {
namespace {

TEST(PromptInputBinding, PRM_012_ValueBasedBinding) {
    const PromptInputBinding binding("user_input", "hello");
    EXPECT_EQ(binding.VariableName(), "user_input");
    EXPECT_EQ(binding.Value(), "hello");
}

TEST(PromptInputBinding, PRM_037_NoOwnershipOfExternalValue) {
    std::string external = "context snapshot";
    const PromptInputBinding binding("context_snapshot", external);
    external = "mutated externally";
    // The binding retains the value it was constructed with; it
    // never holds a reference to the external object and never
    // transfers ownership (PRM-037, TOL-022).
    EXPECT_EQ(binding.Value(), "context snapshot");
}

TEST(PromptInputBinding, Chapter25_EmptyVariableNameRejected) {
    EXPECT_THROW(PromptInputBinding("", "value"), std::invalid_argument);
    EXPECT_THROW(PromptInputBinding("   ", "value"), std::invalid_argument);
}

TEST(PromptInputBinding, PRM_012_Immutability) {
    const PromptInputBinding binding("var", "1");
    const PromptInputBinding copy = binding;
    EXPECT_EQ(copy.VariableName(), "var");
    EXPECT_EQ(copy.Value(), "1");
}

}  // namespace
}  // namespace ak::prompt