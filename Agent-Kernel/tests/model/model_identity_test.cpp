// ============================================================
// model_identity_test.cpp - P1-IS008 Rev1.0 Chapter 7
// ============================================================
// ModelId value-type tests: canonical identity convention
// (non-empty, non-whitespace), immutability, equality, and
// construction-failure semantics (InvalidInput category,
// Chapter 14).
// ============================================================

#include <agent_kernel/model/model_identity.hpp>

#include <gtest/gtest.h>

#include <stdexcept>
#include <string>
#include <type_traits>

namespace ak::model {
namespace {

TEST(ModelIdentity, AcceptsValidValue) {
    const ModelId id("deterministic-model");
    EXPECT_EQ(id.Value(), "deterministic-model");
}

TEST(ModelIdentity, Equality) {
    const ModelId a("model-a");
    const ModelId b("model-a");
    const ModelId c("model-b");
    EXPECT_EQ(a, b);
    EXPECT_NE(a, c);
}

TEST(ModelIdentity, RejectsEmptyValue) {
    EXPECT_THROW(ModelId(""), std::invalid_argument);
}

TEST(ModelIdentity, RejectsWhitespaceOnlyValue) {
    EXPECT_THROW(ModelId("   "), std::invalid_argument);
    EXPECT_THROW(ModelId("\t\n"), std::invalid_argument);
}

TEST(ModelIdentity, NotDefaultConstructible) {
    // ModelId has no default constructor; a Model always
    // carries an identity (Chapter 7 traceability).
    static_assert(!std::is_default_constructible_v<ModelId>);
}

}  // namespace
}  // namespace ak::model
