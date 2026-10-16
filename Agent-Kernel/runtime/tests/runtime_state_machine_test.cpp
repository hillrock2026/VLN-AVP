#include <gtest/gtest.h>
#include <runtime_state_machine.h>

namespace ak::runtime {
namespace {

TEST(RuntimeStateMachineTest, InitialStateIsCreated) {
    RuntimeStateMachine sm;
    EXPECT_EQ(sm.GetState(), RuntimeState::kCreated);
    EXPECT_FALSE(sm.IsTerminal());
}

TEST(RuntimeStateMachineTest, CreatedToRunningIsValid) {
    RuntimeStateMachine sm;
    EXPECT_TRUE(sm.CanTransitionTo(RuntimeState::kRunning));
    EXPECT_TRUE(sm.TransitionTo(RuntimeState::kRunning));
    EXPECT_EQ(sm.GetState(), RuntimeState::kRunning);
}

TEST(RuntimeStateMachineTest, CreatedToFailedIsValid) {
    RuntimeStateMachine sm;
    EXPECT_TRUE(sm.CanTransitionTo(RuntimeState::kFailed));
    EXPECT_TRUE(sm.TransitionTo(RuntimeState::kFailed));
    EXPECT_EQ(sm.GetState(), RuntimeState::kFailed);
    EXPECT_TRUE(sm.IsTerminal());
}

TEST(RuntimeStateMachineTest, RunningToStoppedIsValid) {
    RuntimeStateMachine sm;
    (void)sm.TransitionTo(RuntimeState::kRunning);
    EXPECT_TRUE(sm.CanTransitionTo(RuntimeState::kStopped));
    EXPECT_TRUE(sm.TransitionTo(RuntimeState::kStopped));
    EXPECT_EQ(sm.GetState(), RuntimeState::kStopped);
    EXPECT_TRUE(sm.IsTerminal());
}

TEST(RuntimeStateMachineTest, RunningToFailedIsValid) {
    RuntimeStateMachine sm;
    (void)sm.TransitionTo(RuntimeState::kRunning);
    EXPECT_TRUE(sm.CanTransitionTo(RuntimeState::kFailed));
    EXPECT_TRUE(sm.TransitionTo(RuntimeState::kFailed));
    EXPECT_EQ(sm.GetState(), RuntimeState::kFailed);
    EXPECT_TRUE(sm.IsTerminal());
}

TEST(RuntimeStateMachineTest, CreatedToStoppedIsInvalid) {
    RuntimeStateMachine sm;
    EXPECT_FALSE(sm.CanTransitionTo(RuntimeState::kStopped));
    EXPECT_FALSE(sm.TransitionTo(RuntimeState::kStopped));
    EXPECT_EQ(sm.GetState(), RuntimeState::kCreated);
}

TEST(RuntimeStateMachineTest, StoppedToRunningIsInvalid) {
    RuntimeStateMachine sm;
    (void)sm.TransitionTo(RuntimeState::kRunning);
    (void)sm.TransitionTo(RuntimeState::kStopped);
    EXPECT_FALSE(sm.CanTransitionTo(RuntimeState::kRunning));
    EXPECT_FALSE(sm.TransitionTo(RuntimeState::kRunning));
    EXPECT_EQ(sm.GetState(), RuntimeState::kStopped);
}

TEST(RuntimeStateMachineTest, FailedToAnyIsInvalid) {
    RuntimeStateMachine sm;
    (void)sm.TransitionTo(RuntimeState::kFailed);
    EXPECT_FALSE(sm.CanTransitionTo(RuntimeState::kCreated));
    EXPECT_FALSE(sm.CanTransitionTo(RuntimeState::kRunning));
    EXPECT_FALSE(sm.CanTransitionTo(RuntimeState::kStopped));
    EXPECT_FALSE(sm.TransitionTo(RuntimeState::kCreated));
    EXPECT_FALSE(sm.TransitionTo(RuntimeState::kRunning));
    EXPECT_FALSE(sm.TransitionTo(RuntimeState::kStopped));
    EXPECT_EQ(sm.GetState(), RuntimeState::kFailed);
}

TEST(RuntimeStateMachineTest, StoppedIsTerminal) {
    RuntimeStateMachine sm;
    (void)sm.TransitionTo(RuntimeState::kRunning);
    (void)sm.TransitionTo(RuntimeState::kStopped);
    EXPECT_TRUE(sm.IsTerminal());
}

TEST(RuntimeStateMachineTest, FailedIsTerminal) {
    RuntimeStateMachine sm;
    (void)sm.TransitionTo(RuntimeState::kFailed);
    EXPECT_TRUE(sm.IsTerminal());
}

TEST(RuntimeStateMachineTest, CreatedIsNotTerminal) {
    RuntimeStateMachine sm;
    EXPECT_FALSE(sm.IsTerminal());
}

TEST(RuntimeStateMachineTest, RunningIsNotTerminal) {
    RuntimeStateMachine sm;
    (void)sm.TransitionTo(RuntimeState::kRunning);
    EXPECT_FALSE(sm.IsTerminal());
}

TEST(RuntimeStateMachineTest, ResetFromStoppedSucceeds) {
    RuntimeStateMachine sm;
    (void)sm.TransitionTo(RuntimeState::kRunning);
    (void)sm.TransitionTo(RuntimeState::kStopped);
    EXPECT_TRUE(sm.Reset());
    EXPECT_EQ(sm.GetState(), RuntimeState::kCreated);
}

TEST(RuntimeStateMachineTest, ResetFromNonTerminalFails) {
    RuntimeStateMachine sm;
    EXPECT_FALSE(sm.Reset());
    EXPECT_EQ(sm.GetState(), RuntimeState::kCreated);
}

TEST(RuntimeStateMachineTest, ResetFromRunningFails) {
    RuntimeStateMachine sm;
    (void)sm.TransitionTo(RuntimeState::kRunning);
    EXPECT_FALSE(sm.Reset());
    EXPECT_EQ(sm.GetState(), RuntimeState::kRunning);
}

}  // namespace
}  // namespace ak::runtime