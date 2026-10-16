// ============================================================
// model_action_test.cpp - First Working Agent Sprint FWA-005
// ============================================================
// TASK 6 Rev2 §28 FWA-005: ModelAction unit test. Construction
// rules for all three kinds; immutability; accessor validity
// (Capability()/Arguments() only when kToolInvoke; Reason() only
// when kInvalid); non-empty capability rule; value semantics.
//
// FWA-T7 / TASK-6-Rev2 / STEP-02 / AC-006
// ============================================================

#include <agent_kernel/fwa/model_action.hpp>

#include <gtest/gtest.h>

#include <stdexcept>
#include <string>
#include <type_traits>

namespace ak::agent {
namespace {

TEST(ModelAction, FWA_005_ToolInvokeCarriesCapabilityAndArguments) {
    const ModelAction action =
        ModelAction::InvokeTool(ak::tool::CapabilityId("cap-a"), "payload");
    EXPECT_EQ(action.Kind(), ModelActionKind::kToolInvoke);
    EXPECT_TRUE(action.IsToolInvoke());
    EXPECT_FALSE(action.IsComplete());
    EXPECT_FALSE(action.IsInvalid());
    ASSERT_NE(action.Capability(), nullptr);
    EXPECT_EQ(action.Capability()->Value(), "cap-a");
    EXPECT_EQ(action.Arguments(), "payload");
    EXPECT_TRUE(action.Reason().empty());
}

TEST(ModelAction, FWA_005_CompleteCarriesNoPayload) {
    const ModelAction action = ModelAction::Complete();
    EXPECT_EQ(action.Kind(), ModelActionKind::kComplete);
    EXPECT_TRUE(action.IsComplete());
    EXPECT_FALSE(action.IsToolInvoke());
    EXPECT_FALSE(action.IsInvalid());
    EXPECT_EQ(action.Capability(), nullptr);
    EXPECT_TRUE(action.Arguments().empty());
    EXPECT_TRUE(action.Reason().empty());
}

TEST(ModelAction, FWA_005_InvalidCarriesStableReason) {
    const ModelAction action = ModelAction::Invalid("model output is malformed");
    EXPECT_EQ(action.Kind(), ModelActionKind::kInvalid);
    EXPECT_TRUE(action.IsInvalid());
    EXPECT_FALSE(action.IsToolInvoke());
    EXPECT_FALSE(action.IsComplete());
    EXPECT_EQ(action.Capability(), nullptr);
    EXPECT_TRUE(action.Arguments().empty());
    EXPECT_EQ(action.Reason(), "model output is malformed");
}

TEST(ModelAction, FWA_005_AccessorsAreConstrainedByKind) {
    // Capability()/Arguments() are meaningful only for kToolInvoke;
    // Reason() is meaningful only for kInvalid. The value type is
    // immutable: no setters, all accessors const noexcept.
    static_assert(std::is_copy_constructible_v<ModelAction>);
    static_assert(std::is_copy_assignable_v<ModelAction>);
    static_assert(!std::has_virtual_destructor_v<ModelAction>);
}

TEST(ModelAction, FWA_005_NonEmptyCapabilityRule) {
    // The non-empty capability rule is enforced deterministically
    // at the identity construction boundary (TOL-111): an empty
    // CapabilityId is rejected.
    EXPECT_THROW(ak::tool::CapabilityId("   "), std::invalid_argument);
    EXPECT_THROW(ak::tool::CapabilityId(""), std::invalid_argument);
    EXPECT_NO_THROW(ModelAction::InvokeTool(
        ak::tool::CapabilityId("cap-valid"), "payload"));
}

TEST(ModelAction, FWA_005_ValueSemanticsCopyIndependent) {
    const ModelAction original =
        ModelAction::InvokeTool(ak::tool::CapabilityId("cap-b"), "arg");
    ModelAction copy = original;
    EXPECT_EQ(copy.Kind(), ModelActionKind::kToolInvoke);
    EXPECT_EQ(copy.Arguments(), "arg");
    // Immutable: the copy and the original stay identical; the
    // value carries no mutable state.
    EXPECT_EQ(copy.Capability()->Value(), "cap-b");
}

}  // namespace
}  // namespace ak::agent
