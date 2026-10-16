#include <gtest/gtest.h>
#include <memory>
#include <runtime.h>
#include <runtime_configuration.h>
#include <agent_kernel/session.hpp>
#include <agent_kernel/session/session_configuration.hpp>
#include <agent_kernel/session/session_builder.hpp>

namespace ak::runtime {

// ============================================================
// RuntimeTestAccess - friend access to the CAP0006-002 test seam
// ============================================================
// Arms the deterministic fault-injection seam used to verify that
// unexpected implementation exceptions are translated into
// RuntimeResult objects (AK0035 7.9 / 17.5).
struct RuntimeTestAccess {
    static void InjectUnexpectedFailure(Runtime& runtime) {
        runtime.injectFailureForTesting_ = true;
    }
};

namespace {

std::unique_ptr<ak::Session> CreateReadySession() {
    auto session = ak::SessionBuilder()
        .WithID(ak::SessionID(1))
        .WithName("P0R0001_Test_Session")
        .WithMaxWorkflows(0)
        .Build();

    session->Initialize();
    session->Activate();
    return session;
}

// ============================================================
// Construction
// ============================================================
TEST(RuntimeTest, ConstructionSucceeds) {
    Runtime runtime;
    EXPECT_FALSE(runtime.IsRunning());
}

// ============================================================
// Run()
// ============================================================
TEST(RuntimeTest, RunWithReadySessionSucceeds) {
    Runtime runtime;
    auto session = CreateReadySession();

    RuntimeResult result = runtime.Run(*session);

    EXPECT_EQ(result.status, RuntimeStatus::kCompleted);
    EXPECT_TRUE(result.IsSuccess());
    EXPECT_EQ(result.workflowsTotal, 0);
    EXPECT_EQ(result.workflowsCompleted, 0);
    EXPECT_EQ(result.workflowsFailed, 0);
    EXPECT_EQ(result.tasksTotal, 0);
    EXPECT_EQ(result.tasksCompleted, 0);
    EXPECT_EQ(result.tasksFailed, 0);
}

TEST(RuntimeTest, RunTransitionsToRunning) {
    Runtime runtime;
    auto session = CreateReadySession();

    EXPECT_FALSE(runtime.IsRunning());
    runtime.Run(*session);
    EXPECT_TRUE(runtime.IsRunning());
}

TEST(RuntimeTest, DoubleRunFails) {
    Runtime runtime;
    auto session = CreateReadySession();

    RuntimeResult r1 = runtime.Run(*session);
    EXPECT_TRUE(r1.IsSuccess());

    RuntimeResult r2 = runtime.Run(*session);
    EXPECT_EQ(r2.status, RuntimeStatus::kInternalError);
    EXPECT_FALSE(r2.IsSuccess());
}

TEST(RuntimeTest, RunWithInvalidSessionStateFails) {
    Runtime runtime;
    auto session = ak::SessionBuilder()
        .WithID(ak::SessionID(2))
        .WithName("UninitializedSession")
        .WithMaxWorkflows(0)
        .Build();
    // Session is in kCreated — NOT kReady.

    RuntimeResult result = runtime.Run(*session);
    EXPECT_EQ(result.status, RuntimeStatus::kInvalidSession);
    EXPECT_FALSE(result.IsSuccess());
}

// ============================================================
// Stop()
// ============================================================
TEST(RuntimeTest, StopAfterRunSucceeds) {
    Runtime runtime;
    auto session = CreateReadySession();

    runtime.Run(*session);
    EXPECT_TRUE(runtime.IsRunning());

    runtime.Stop();
    EXPECT_FALSE(runtime.IsRunning());

    // Verify terminal behavior: Run() after Stop() fails.
    RuntimeResult result = runtime.Run(*session);
    EXPECT_EQ(result.status, RuntimeStatus::kInternalError);
}

TEST(RuntimeTest, StopWithoutRunIsNoOp) {
    Runtime runtime;
    EXPECT_FALSE(runtime.IsRunning());
    runtime.Stop();  // Must not crash.
    EXPECT_FALSE(runtime.IsRunning());
}

TEST(RuntimeTest, DoubleStopIsSafe) {
    Runtime runtime;
    auto session = CreateReadySession();

    runtime.Run(*session);
    EXPECT_TRUE(runtime.IsRunning());

    runtime.Stop();
    runtime.Stop();  // Second Stop must be safe.
    EXPECT_FALSE(runtime.IsRunning());
}

// ============================================================
// Run -> Stop -> Run (reset not supported in P0R0001)
// ============================================================
TEST(RuntimeTest, RunAfterStopFails) {
    Runtime runtime;
    auto session = CreateReadySession();

    runtime.Run(*session);
    runtime.Stop();

    RuntimeResult result = runtime.Run(*session);
    EXPECT_EQ(result.status, RuntimeStatus::kInternalError);
}

// ============================================================
// IsRunning()
// ============================================================
TEST(RuntimeTest, IsRunningReflectsLifecycle) {
    Runtime runtime;

    EXPECT_FALSE(runtime.IsRunning());  // kCreated

    auto session = CreateReadySession();
    runtime.Run(*session);
    EXPECT_TRUE(runtime.IsRunning());   // kRunning

    runtime.Stop();
    EXPECT_FALSE(runtime.IsRunning());  // kStopped
}

// ============================================================
// Component Access (AK0030-I4 typed references)
// ============================================================
TEST(RuntimeTest, GetSchedulerReturnsReference) {
    Runtime runtime;
    Scheduler& ref = runtime.GetScheduler();
    // Verify we get a valid reference (no crash, no nullptr).
    EXPECT_EQ(&ref, &runtime.GetScheduler());
}

TEST(RuntimeTest, GetExecutorReturnsReference) {
    Runtime runtime;
    Executor& ref = runtime.GetExecutor();
    EXPECT_EQ(&ref, &runtime.GetExecutor());
}

TEST(RuntimeTest, GetResolverReturnsReference) {
    Runtime runtime;
    CapabilityResolver& ref = runtime.GetResolver();
    EXPECT_EQ(&ref, &runtime.GetResolver());
}

TEST(RuntimeTest, GetEventBusReturnsReference) {
    Runtime runtime;
    EventBus& ref = runtime.GetEventBus();
    EXPECT_EQ(&ref, &runtime.GetEventBus());
}


// ============================================================
// CAP0006-002 ? Runtime Public Exception Boundary
// ============================================================
TEST(RuntimeTest, UnexpectedInternalExceptionIsTranslatedToRuntimeResult) {
    Runtime runtime;
    auto session = CreateReadySession();

    RuntimeTestAccess::InjectUnexpectedFailure(runtime);

    // AK0035 7.9 / 17.5: implementation exceptions shall not
    // propagate through the Runtime Public API. The unexpected
    // failure must be converted into a RuntimeResult.
    RuntimeResult result;
    EXPECT_NO_THROW(result = runtime.Run(*session));

    EXPECT_EQ(result.status, RuntimeStatus::kInternalError);
    EXPECT_FALSE(result.IsSuccess());

    // Execution terminates safely: Runtime lifecycle is consistent.
    EXPECT_FALSE(runtime.IsRunning());
}

TEST(RuntimeTest, UnexpectedInternalExceptionPreservesLifecycleConsistency) {
    Runtime runtime;
    auto session = CreateReadySession();

    RuntimeTestAccess::InjectUnexpectedFailure(runtime);
    RuntimeResult failed = runtime.Run(*session);
    EXPECT_EQ(failed.status, RuntimeStatus::kInternalError);
    EXPECT_FALSE(runtime.IsRunning());

    // The Runtime remains terminally consistent: subsequent calls
    // are rejected safely and never escape an exception.
    RuntimeResult again = runtime.Run(*session);
    EXPECT_EQ(again.status, RuntimeStatus::kInternalError);
    EXPECT_NO_THROW(runtime.Stop());
    EXPECT_FALSE(runtime.IsRunning());
}

TEST(RuntimeTest, ExceptionBoundaryDoesNotAffectSuccessfulExecution) {
    Runtime runtime;
    auto session = CreateReadySession();

    // No injection armed: normal execution behavior is unchanged.
    RuntimeResult result = runtime.Run(*session);
    EXPECT_TRUE(result.IsSuccess());
    EXPECT_EQ(result.status, RuntimeStatus::kCompleted);
    EXPECT_TRUE(runtime.IsRunning());

    runtime.Stop();
    EXPECT_FALSE(runtime.IsRunning());
}

}  // namespace
}  // namespace ak::runtime