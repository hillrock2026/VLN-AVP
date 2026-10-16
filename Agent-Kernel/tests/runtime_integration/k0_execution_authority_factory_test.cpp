// ============================================================
// k0_execution_authority_factory_test.cpp
// ============================================================
// Narrowly scoped evidence for the Kernel-issued execution
// authority factory introduced by K0-BLOCKER-REMEDIATION-05
// (INV-K0-FWA-RUNTIME-AUTHORITY):
//
//   ak::runtime_integration::IssueRuntimeExecutionAuthority(Runtime&)
//     -> RuntimeExecutionAuthorityHandle (move-only, Kernel-owned ctor)
//     -> handle.Port()  (the Kernel-bound RuntimeInteractionPort)
//     -> Submit(RuntimeInvocationRequest) -> Runtime::Run
//     -> Observe(request_id) -> RuntimeObservation
//
// This test uses the REAL Kernel Runtime and the REAL factory-issued
// adapter. It does NOT construct RuntimePublicApiAdapter directly and
// does NOT supply a substitute port: the authorization is obtained
// only through the sanctioned factory.
//
// LIMITS OF THIS EVIDENCE (do not overstate):
//   * RuntimePublicApiAdapter still has a public constructor and
//     Runtime::Run is still publicly reachable, so the handle/factory
//     is the intended authorized integration path, NOT a universal
//     type-level boundary for arbitrary consumers.
//   * Capability permission/resource constraints are represented in
//     the K0 contract headers but are NOT enforced by this runtime.
//   * This does not close K0 and does not establish production safety.
//
// The capability used here ("test.echo") is a test-domain capability
// registered through the sanctioned Runtime::RegisterCapability path.
// No navigation/robot capability is defined or invoked.
// ============================================================

#include <agent_kernel/runtime_integration/runtime_execution_authority.hpp>

#include <runtime.h>

#include <agent_kernel/agent/runtime/runtime_interaction_port.hpp>
#include <agent_kernel/agent/runtime/runtime_invocation_request.hpp>
#include <agent_kernel/agent/runtime/runtime_observation.hpp>
#include <agent_kernel/agent/runtime/runtime_submission_result.hpp>

#include <gtest/gtest.h>

#include <memory>
#include <optional>
#include <string>
#include <type_traits>
#include <utility>

namespace {

using ak::agent::ObservationStatus;
using ak::agent::RuntimeInvocationRequest;
using ak::agent::RuntimeObservation;
using ak::agent::RuntimeRequestId;
using ak::agent::RuntimeSubmissionResult;
using ak::agent::SubmissionStatus;
using ak::runtime_integration::IssueRuntimeExecutionAuthority;
using ak::runtime_integration::RuntimeExecutionAuthorityHandle;

constexpr const char* kCapabilityId = "test.echo";
constexpr const char* kProviderId = "test.provider";
constexpr const char* kEchoPrefix = "[kernel-echo]:";

// ---- Compile-time contract of the authority handle -----------------
// Kernel-owned construction: no public construction from any port.
static_assert(
    !std::is_constructible_v<RuntimeExecutionAuthorityHandle,
                             std::unique_ptr<ak::agent::RuntimeInteractionPort>>,
    "the handle must not be publicly constructible from a port");
static_assert(
    !std::is_constructible_v<RuntimeExecutionAuthorityHandle,
                             ak::agent::RuntimeInteractionPort&>,
    "the handle must not be publicly constructible from a port reference");
static_assert(
    !std::is_convertible_v<ak::agent::RuntimeInteractionPort*,
                           RuntimeExecutionAuthorityHandle>,
    "there must be no implicit conversion from a port to the handle");

// Move-only value semantics.
static_assert(std::is_default_constructible_v<RuntimeExecutionAuthorityHandle>);
static_assert(std::is_move_constructible_v<RuntimeExecutionAuthorityHandle>);
static_assert(std::is_move_assignable_v<RuntimeExecutionAuthorityHandle>);
static_assert(!std::is_copy_constructible_v<RuntimeExecutionAuthorityHandle>);
static_assert(!std::is_copy_assignable_v<RuntimeExecutionAuthorityHandle>);

std::string EchoInvoker(int& counter, const std::string& payload) {
    ++counter;
    return std::string(kEchoPrefix) + payload;
}

}  // namespace

// 1. The factory issues a bound, usable authority handle.
TEST(K0ExecutionAuthorityFactory, FactoryIssuesBoundHandle) {
    ak::runtime::Runtime runtime;
    RuntimeExecutionAuthorityHandle authority =
        IssueRuntimeExecutionAuthority(runtime);
    EXPECT_TRUE(authority.IsBound());

    ak::agent::RuntimeInteractionPort& port = authority.Port();
    EXPECT_EQ(&port, &authority.Port());
}

// 2. Move-only lifetime: a move transfers authority and leaves the
//    source handle unbound.
TEST(K0ExecutionAuthorityFactory, MoveTransfersAuthorityAndLeavesSourceUnbound) {
    ak::runtime::Runtime runtime;
    RuntimeExecutionAuthorityHandle source =
        IssueRuntimeExecutionAuthority(runtime);
    ASSERT_TRUE(source.IsBound());

    RuntimeExecutionAuthorityHandle moved = std::move(source);
    EXPECT_TRUE(moved.IsBound());
    EXPECT_FALSE(source.IsBound());
}

// 3. A default-constructed handle carries no authority.
TEST(K0ExecutionAuthorityFactory, DefaultConstructedHandleIsUnbound) {
    RuntimeExecutionAuthorityHandle unbound;
    EXPECT_FALSE(unbound.IsBound());
    // Deliberately do NOT call Port(): using an unbound handle is a
    // caller error (IsBound() must be checked first).
}

// 4. Real Submit -> Run -> Observe through the authorized port, using a
//    capability registered through the sanctioned Runtime path.
TEST(K0ExecutionAuthorityFactory, AuthorizedPortExecutesRegisteredCapability) {
    ak::runtime::Runtime runtime;
    int invocations = 0;
    runtime.RegisterCapability(
        kCapabilityId, kProviderId,
        [&invocations](const std::string& payload) {
            return EchoInvoker(invocations, payload);
        });

    RuntimeExecutionAuthorityHandle authority =
        IssueRuntimeExecutionAuthority(runtime);
    ASSERT_TRUE(authority.IsBound());

    const RuntimeSubmissionResult submission = authority.Port().Submit(
        RuntimeInvocationRequest{RuntimeRequestId("auth-factory-1"),
                                 kCapabilityId, "hello"});
    EXPECT_TRUE(submission.accepted);
    EXPECT_EQ(submission.status, SubmissionStatus::kCompleted);
    EXPECT_TRUE(submission.failure.empty());
    EXPECT_EQ(invocations, 1);  // the real invoker ran exactly once

    const RuntimeObservation observation =
        authority.Port().Observe(RuntimeRequestId("auth-factory-1"));
    EXPECT_EQ(observation.status, ObservationStatus::kSuccess);
    EXPECT_EQ(observation.capability_id, kCapabilityId);
    EXPECT_EQ(observation.output, std::string(kEchoPrefix) + "hello");
    EXPECT_TRUE(observation.failure.empty());

    // Independent evidence from the Runtime Public API (not the port).
    const std::optional<ak::ExecutionResult> per_invocation =
        runtime.GetInvocationResult("auth-factory-1");
    ASSERT_TRUE(per_invocation.has_value());
    EXPECT_TRUE(per_invocation->IsSuccess());

    runtime.Stop();
}

// 5. An unknown capability is accepted then deterministically fails, and
//    nothing is executed.
TEST(K0ExecutionAuthorityFactory, UnknownCapabilityFailsWithoutExecuting) {
    ak::runtime::Runtime runtime;
    int invocations = 0;
    runtime.RegisterCapability(
        kCapabilityId, kProviderId,
        [&invocations](const std::string& payload) {
            return EchoInvoker(invocations, payload);
        });

    RuntimeExecutionAuthorityHandle authority =
        IssueRuntimeExecutionAuthority(runtime);
    ASSERT_TRUE(authority.IsBound());

    const RuntimeSubmissionResult submission = authority.Port().Submit(
        RuntimeInvocationRequest{RuntimeRequestId("auth-unknown-1"),
                                 "no.such.capability", "payload"});
    EXPECT_TRUE(submission.accepted);
    EXPECT_EQ(submission.status, SubmissionStatus::kFailed);
    EXPECT_NE(submission.failure.find("capability-not-found:"),
              std::string::npos);
    EXPECT_EQ(invocations, 0);

    const RuntimeObservation observation =
        authority.Port().Observe(RuntimeRequestId("auth-unknown-1"));
    EXPECT_EQ(observation.status, ObservationStatus::kFailure);

    runtime.Stop();
}

// 6. Blank capability_id / payload is rejected before any execution.
TEST(K0ExecutionAuthorityFactory, BlankFieldsAreRejectedWithoutExecuting) {
    ak::runtime::Runtime runtime;
    int invocations = 0;
    runtime.RegisterCapability(
        kCapabilityId, kProviderId,
        [&invocations](const std::string& payload) {
            return EchoInvoker(invocations, payload);
        });

    RuntimeExecutionAuthorityHandle authority =
        IssueRuntimeExecutionAuthority(runtime);
    ASSERT_TRUE(authority.IsBound());

    const RuntimeSubmissionResult blank_capability = authority.Port().Submit(
        RuntimeInvocationRequest{RuntimeRequestId("auth-blank-1"), "",
                                 "payload"});
    EXPECT_FALSE(blank_capability.accepted);
    EXPECT_EQ(blank_capability.status, SubmissionStatus::kRejected);

    const RuntimeSubmissionResult blank_payload = authority.Port().Submit(
        RuntimeInvocationRequest{RuntimeRequestId("auth-blank-2"),
                                 kCapabilityId, "   "});
    EXPECT_FALSE(blank_payload.accepted);
    EXPECT_EQ(blank_payload.status, SubmissionStatus::kRejected);

    EXPECT_EQ(invocations, 0);
}

// 7. Observing a never-submitted request never fabricates success.
TEST(K0ExecutionAuthorityFactory, ObserveWithoutSubmitNeverFabricatesSuccess) {
    ak::runtime::Runtime runtime;
    RuntimeExecutionAuthorityHandle authority =
        IssueRuntimeExecutionAuthority(runtime);

    const RuntimeObservation observation =
        authority.Port().Observe(RuntimeRequestId("auth-never-submitted"));
    EXPECT_NE(observation.status, ObservationStatus::kSuccess);
    EXPECT_NE(observation.failure.find("result-not-found:"), std::string::npos);

    runtime.Stop();
}
