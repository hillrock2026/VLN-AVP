// ============================================================
// prompt_identity_test.cpp - P1-IS007 Rev1.1 Chapter 33
// ============================================================
// Identity tests: empty identity rejection (Chapter 25.1),
// identity equality and immutability (PRM-001), stable
// identity semantics (AC-002), and model-neutral identity
// (PRM-016).
// ============================================================

#include <agent_kernel/prompt/prompt_identity.hpp>

#include <gtest/gtest.h>

#include <stdexcept>
#include <string>
#include <type_traits>

namespace ak::prompt {
namespace {

TEST(PromptIdentity, PRM_001_EmptyIdentityRejected) {
    EXPECT_THROW(PromptId(""), std::invalid_argument);
    EXPECT_THROW(PromptId("   "), std::invalid_argument);
    EXPECT_THROW(PromptId("\t"), std::invalid_argument);
    EXPECT_THROW(PromptId(" \n"), std::invalid_argument);
}

TEST(PromptIdentity, PRM_001_ValueSemanticsAndImmutability) {
    const PromptId id("kernel-prompt");
    EXPECT_EQ(id.Value(), "kernel-prompt");
    EXPECT_FALSE(id.Empty());
    EXPECT_EQ(id, PromptId("kernel-prompt"));
    EXPECT_NE(id, PromptId("other-prompt"));

    const PromptId copy = id;
    EXPECT_EQ(copy, id);
    EXPECT_EQ(copy.Value(), "kernel-prompt");
}

TEST(PromptIdentity, AC_002_NotDefaultConstructible) {
    static_assert(!std::is_default_constructible_v<PromptId>,
                  "PromptId must be constructed with an identity value");
    static_assert(std::is_copy_constructible_v<PromptId>);
    static_assert(std::is_copy_assignable_v<PromptId>);
}

TEST(PromptIdentity, PRM_016_IdentityIsModelNeutral) {
    // PromptId is an opaque immutable value; it carries no
    // provider-specific model identity semantics (Chapter 8.1).
    const PromptId id("prompt-a");
    EXPECT_EQ(id.Value(), "prompt-a");
}

}  // namespace
}  // namespace ak::prompt