// ============================================================
// conformance_test.cpp - P1-IS001 structural conformance
// ============================================================
// Compile-time and behavioral checks that Foundation
// components:
// - provide only neutral implementation support;
// - expose no Runtime internal types (this TU includes only
//   Foundation headers - the static boundary check verifies
//   the headers themselves);
// - do not coordinate architectural subsystems;
// - remain below the owner-specific representation.
// ============================================================

#include <agent_kernel/foundation/kernel_contracts.hpp>
#include <agent_kernel/foundation/kernel_diagnostics.hpp>
#include <agent_kernel/foundation/kernel_handle.hpp>
#include <agent_kernel/foundation/kernel_identity.hpp>
#include <agent_kernel/foundation/kernel_lifecycle.hpp>
#include <agent_kernel/foundation/kernel_metadata.hpp>
#include <agent_kernel/foundation/kernel_object.hpp>
#include <agent_kernel/foundation/kernel_observer.hpp>
#include <agent_kernel/foundation/kernel_registry.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <memory>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

// NOTE: This translation unit intentionally includes NO
// subsystem headers (Agent, Memory, Context, Planner, Tool,
// Execution Composition) and NO Runtime headers. If any
// Foundation public header leaked such a type, the static
// boundary check (check_foundation_boundaries.cmake) fails
// at the include level, and this file would require those
// includes to compile.

namespace ak {
namespace {

// ------------------------------------------------------------
// Test-local architectural owner representation
// ------------------------------------------------------------
// A minimal owner-shaped object that composes Foundation
// mechanisms. The object is the architectural owner: the
// Foundation pieces are neutral support below it.
class OwnerRepresentation {
public:
    explicit OwnerRepresentation(KernelIdentity identity,
                                 LifecycleTransitionValidator::Rule rule)
        : identity_(identity), validator_(rule) {}

    void SetMetadata(KernelMetadata metadata) {
        metadata_ = std::move(metadata);
    }

    [[nodiscard]] const KernelMetadata& GetMetadata() const noexcept {
        return metadata_;
    }

    [[nodiscard]] KernelIdentity GetIdentity() const noexcept {
        return identity_;
    }

    [[nodiscard]] TransitionResult RequestTransition(
        std::uint8_t from, std::uint8_t to) const {
        // The owner initiates and the owner supplies the rule;
        // the Foundation only validates.
        return validator_.Validate(from, to);
    }

    DiagnosticSink& Diagnostics() noexcept { return diagnostics_; }

    OwnerScopedRegistry<KernelIdentity, int>& Values() noexcept {
        return values_;
    }

private:
    KernelIdentity identity_;
    KernelMetadata metadata_;
    LifecycleTransitionValidator validator_;
    DiagnosticSink diagnostics_;
    OwnerScopedRegistry<KernelIdentity, int> values_;
};

bool OwnerRule(std::uint8_t from, std::uint8_t to) noexcept {
    return from == 0 && to == 1;
}

TEST(FoundationConformance, ComponentsAreNeutralSupport) {
    // The owner representation composes neutral Foundation
    // mechanisms; each mechanism behaves as support and cannot
    // coordinate or mutate anything outside the object.
    OwnerRepresentation owner(KernelIdentity(1), OwnerRule);

    KernelMetadata metadata;
    metadata.name = "owner";
    owner.SetMetadata(metadata);
    EXPECT_EQ(owner.GetMetadata().name, "owner");
    EXPECT_EQ(owner.GetIdentity(), KernelIdentity(1));

    // Lifecycle validation is owner-initiated.
    EXPECT_TRUE(owner.RequestTransition(0, 1).Accepted());
    EXPECT_TRUE(owner.RequestTransition(0, 2).Rejected());

    // Diagnostics are owner-scoped.
    owner.Diagnostics().Add(DiagnosticSeverity::kError, 1, "owner issue");
    EXPECT_TRUE(owner.Diagnostics().HasErrors());

    // Registration is owner-scoped containment.
    owner.Values().Register(KernelIdentity(9),
                            std::make_unique<int>(42));
    ASSERT_NE(owner.Values().Find(KernelIdentity(9)), nullptr);
    EXPECT_EQ(*owner.Values().Find(KernelIdentity(9)), 42);
}

TEST(FoundationConformance, PublicTypesAreNeutralValues) {
    // Identity, metadata, state, and diagnostics are neutral
    // value types usable in generic containers.
    static_assert(std::is_copy_constructible_v<KernelIdentity>);
    static_assert(std::is_copy_constructible_v<KernelMetadata>);
    static_assert(std::is_copy_constructible_v<LifecycleState>);
    static_assert(std::is_copy_constructible_v<TransitionResult>);
    static_assert(std::is_copy_constructible_v<KernelDiagnostic>);

    // Handles and registries are templates: no concrete
    // subsystem type is required to use them.
    static_assert(std::is_same_v<KernelHandle<int, KernelIdentity>::IDT,
                                 KernelIdentity>);
}

TEST(FoundationConformance, NoCoordinatorSurfaceOnServices) {
    // Service-like components (registry, observer registry,
    // diagnostic sink) expose only owner-scoped mechanics and
    // no cross-subsystem coordination API. This is enforced
    // structurally in the dedicated test files; this test
    // confirms the components compile against Foundation-only
    // headers without any subsystem types.
    ObserverRegistry observers;
    DiagnosticSink diagnostics;
    OwnerScopedRegistry<KernelIdentity, int> values;

    (void)observers;
    (void)diagnostics;
    (void)values;
}

}  // namespace
}  // namespace ak