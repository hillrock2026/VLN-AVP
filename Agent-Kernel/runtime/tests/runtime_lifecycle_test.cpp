#include <gtest/gtest.h>
#include <runtime_state_machine.h>
#include <runtime_lifecycle_manager.h>

namespace ak::runtime {
namespace {

TEST(RuntimeLifecycleManagerTest, InitializeFromCreatedSucceeds) {
    RuntimeStateMachine sm;
    RuntimeLifecycleManager lm(sm);
    EXPECT_TRUE(lm.Initialize());
    EXPECT_EQ(sm.GetState(), RuntimeState::kRunning);
    EXPECT_FALSE(lm.HasFailed());
}

TEST(RuntimeLifecycleManagerTest, InitializeFromRunningFails) {
    RuntimeStateMachine sm;
    RuntimeLifecycleManager lm(sm);
    (void)lm.Initialize();
    EXPECT_FALSE(lm.Initialize());
    EXPECT_EQ(sm.GetState(), RuntimeState::kRunning);
}

TEST(RuntimeLifecycleManagerTest, InitializeFromStoppedFails) {
    RuntimeStateMachine sm;
    RuntimeLifecycleManager lm(sm);
    (void)lm.Initialize();
    lm.Shutdown();
    EXPECT_FALSE(lm.Initialize());
    EXPECT_EQ(sm.GetState(), RuntimeState::kStopped);
}

TEST(RuntimeLifecycleManagerTest, ShutdownFromRunningSucceeds) {
    RuntimeStateMachine sm;
    RuntimeLifecycleManager lm(sm);
    (void)lm.Initialize();
    lm.Shutdown();
    EXPECT_EQ(sm.GetState(), RuntimeState::kStopped);
}

TEST(RuntimeLifecycleManagerTest, ShutdownFromCreatedIsNoOp) {
    RuntimeStateMachine sm;
    RuntimeLifecycleManager lm(sm);
    lm.Shutdown();
    EXPECT_EQ(sm.GetState(), RuntimeState::kCreated);
}

TEST(RuntimeLifecycleManagerTest, DoubleShutdownIsSafe) {
    RuntimeStateMachine sm;
    RuntimeLifecycleManager lm(sm);
    (void)lm.Initialize();
    lm.Shutdown();
    lm.Shutdown();
    EXPECT_EQ(sm.GetState(), RuntimeState::kStopped);
}

TEST(RuntimeLifecycleManagerTest, FailFromCreatedTransitionsToFailed) {
    RuntimeStateMachine sm;
    RuntimeLifecycleManager lm(sm);
    lm.Fail("initialization error");
    EXPECT_TRUE(lm.HasFailed());
    EXPECT_EQ(lm.GetFailureReason(), "initialization error");
    EXPECT_EQ(sm.GetState(), RuntimeState::kFailed);
}

TEST(RuntimeLifecycleManagerTest, FailFromRunningTransitionsToFailed) {
    RuntimeStateMachine sm;
    RuntimeLifecycleManager lm(sm);
    (void)lm.Initialize();
    lm.Fail("runtime error");
    EXPECT_TRUE(lm.HasFailed());
    EXPECT_EQ(lm.GetFailureReason(), "runtime error");
    EXPECT_EQ(sm.GetState(), RuntimeState::kFailed);
}

TEST(RuntimeLifecycleManagerTest, FailFromTerminalIsNoOp) {
    RuntimeStateMachine sm;
    RuntimeLifecycleManager lm(sm);
    (void)lm.Initialize();
    lm.Shutdown();
    lm.Fail("late error");
    EXPECT_FALSE(lm.HasFailed());
    EXPECT_EQ(sm.GetState(), RuntimeState::kStopped);
}

TEST(RuntimeLifecycleManagerTest, FullLifecycleSucceeds) {
    RuntimeStateMachine sm;
    RuntimeLifecycleManager lm(sm);
    EXPECT_EQ(sm.GetState(), RuntimeState::kCreated);
    EXPECT_TRUE(lm.Initialize());
    EXPECT_EQ(sm.GetState(), RuntimeState::kRunning);
    lm.Shutdown();
    EXPECT_EQ(sm.GetState(), RuntimeState::kStopped);
    EXPECT_TRUE(sm.IsTerminal());
}

}  // namespace
}  // namespace ak::runtime