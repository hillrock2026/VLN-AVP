#include <gtest/gtest.h>
#include <runtime.h>
#include <runtime_executor.h>
#include <capability_resolver.h>
#include <capability_binding.h>
#include <agent_kernel/task.hpp>
#include <agent_kernel/task/task_execution_descriptor.hpp>
#include <agent_kernel/runtime/capability/execution_binding.hpp>

namespace ak::runtime {

// ============================================================
// CapabilityResolverTestAccess — friend access to private methods
// ============================================================
struct CapabilityResolverTestAccess {
    static void Register(CapabilityResolver& r,
                         const std::string& name,
                         const std::string& provider) {
        r.Register(name, provider);
    }
    static void Unregister(CapabilityResolver& r,
                           const std::string& name) {
        r.Unregister(name);
    }
    static std::size_t RegistrySize(const CapabilityResolver& r) {
        return r.RegistrySize();
    }
};

namespace {

// Helper: create a valid task with a given ID and capability name.
ak::Task CreateValidTask(ak::TaskID id, const std::string& capabilityName) {
    ak::TaskExecutionDescriptor desc;
    desc.capability.name = capabilityName;
    return ak::Task(id, ak::WorkflowID(100), desc);
}

// Helper: create a kReady ExecutionBinding for a given capability.
// Helper: create a kReady ExecutionBinding for a given capability.
// C1 (TASK 3.2 Conflict C): the fixture carries a deterministic
// real CapabilityInvoker so existing tests exercise the real
// invocation semantics; the pre-TASK-3.2 synthetic success path
// is removed from production and NOT restored in fixtures.
ak::ExecutionBinding MakeBinding(const std::string& name,
                                 const std::string& provider = "test") {
    ak::CapabilityIdentifier cid;
    cid.name = name;
    cid.provider = provider;
    cid.version = 1;

    ak::ExecutionBinding binding;
    binding.capabilityID = cid;
    binding.status = ak::BindingStatus::kReady;
    binding.payload = "payload:" + name;
    binding.invoker = [name](const std::string& payload) {
        return "echo:" + name + ":" + payload;
    };
    return binding;
}

// Helper: create a descriptor with a given capability name.
ak::TaskExecutionDescriptor MakeDescriptor(const std::string& name) {
    ak::TaskExecutionDescriptor desc;
    desc.capability.name = name;
    return desc;
}

// ============================================================
// Construction
// ============================================================
TEST(ExecutorTest, DefaultConstructionSucceeds) {
    Executor executor;
    SUCCEED();
}

TEST(ExecutorTest, DestructionIsSafe) {
    { Executor executor; }
    SUCCEED();
}

// ============================================================
// Execute Success — kCompleted
// ============================================================
TEST(ExecutorTest, ExecuteReturnsCompletedForValidBinding) {
    Executor executor;
    auto task = CreateValidTask(ak::TaskID(1), "test.capability");
    auto binding = MakeBinding("test.capability");

    auto result = executor.Execute(task, binding);

    EXPECT_EQ(result.status, ak::ExecutionStatus::kCompleted);
    EXPECT_TRUE(result.IsSuccess());
    EXPECT_FALSE(result.IsFailure());
    EXPECT_FALSE(result.message.empty());
    EXPECT_TRUE(result.output.has_value());
    EXPECT_FALSE(result.retryable);
}

TEST(ExecutorTest, CompletedHasOutput) {
    Executor executor;
    auto task = CreateValidTask(ak::TaskID(42), "demo.echo");
    auto binding = MakeBinding("demo.echo");

    auto result = executor.Execute(task, binding);

    EXPECT_EQ(result.status, ak::ExecutionStatus::kCompleted);
    ASSERT_TRUE(result.output.has_value());
    std::string output = std::any_cast<std::string>(result.output.value());
    // OLD (pre-C1): expected the synthetic "completed" marker.
    // NEW (C1): the deterministic fixture invoker's real output.
    EXPECT_EQ(output, "echo:demo.echo:payload:demo.echo");
}

// ============================================================
// Missing invoker - deterministic failure (C1)
// ============================================================
TEST(ExecutorTest, MissingInvokerFailsWithoutSyntheticSuccess) {
    Executor executor;
    auto task = CreateValidTask(ak::TaskID(12), "no.invoker");
    auto binding = MakeBinding("no.invoker");
    // A resolved-but-not-executable capability: no invoker.
    binding.invoker.reset();

    auto result = executor.Execute(task, binding);

    EXPECT_EQ(result.status, ak::ExecutionStatus::kFailed);
    EXPECT_TRUE(result.IsFailure());
    EXPECT_FALSE(result.IsSuccess());
    EXPECT_FALSE(result.output.has_value());
    EXPECT_FALSE(result.retryable);
    // The failure is a deterministic invocation failure; no
    // synthetic completion marker is produced.
    EXPECT_NE(result.message.find("Capability invocation failed"),
              std::string::npos);
}

// ============================================================
// Execute Failure — validation -> kFailed
// ============================================================
TEST(ExecutorTest, ExecuteFailsForEmptyCapabilityName) {
    Executor executor;
    auto task = CreateValidTask(ak::TaskID(2), "");
    auto binding = MakeBinding("");

    auto result = executor.Execute(task, binding);

    EXPECT_EQ(result.status, ak::ExecutionStatus::kFailed);
    EXPECT_TRUE(result.IsFailure());
    EXPECT_FALSE(result.IsSuccess());
    EXPECT_FALSE(result.message.empty());
    EXPECT_NE(result.message.find("empty"), std::string::npos);
    EXPECT_FALSE(result.output.has_value());
}

TEST(ExecutorTest, ExecuteFailsForInvalidTaskZeroId) {
    Executor executor;
    auto task = CreateValidTask(ak::TaskID(0), "test.cap");
    auto binding = MakeBinding("test.cap");

    auto result = executor.Execute(task, binding);

    EXPECT_EQ(result.status, ak::ExecutionStatus::kFailed);
    EXPECT_TRUE(result.IsFailure());
    EXPECT_FALSE(result.message.empty());
    EXPECT_FALSE(result.output.has_value());
}

TEST(ExecutorTest, ExecuteFailsForBindingNotReady) {
    Executor executor;
    auto task = CreateValidTask(ak::TaskID(7), "test.cap");
    auto binding = MakeBinding("test.cap");
    binding.status = ak::BindingStatus::kInvalid;

    auto result = executor.Execute(task, binding);

    EXPECT_EQ(result.status, ak::ExecutionStatus::kFailed);
    EXPECT_TRUE(result.IsFailure());
    EXPECT_NE(result.message.find("kReady"), std::string::npos);
}

// ============================================================
// IsSuccess / IsFailure
// ============================================================
TEST(ExecutorTest, IsSuccessTrueOnlyForCompleted) {
    Executor executor;
    auto task = CreateValidTask(ak::TaskID(1), "t");
    auto binding = MakeBinding("t");

    auto result = executor.Execute(task, binding);
    EXPECT_TRUE(result.IsSuccess());
    EXPECT_FALSE(result.IsFailure());
}

TEST(ExecutorTest, IsFailureTrueForFailed) {
    Executor executor;
    auto task = CreateValidTask(ak::TaskID(3), "x");
    auto binding = MakeBinding("");

    auto result = executor.Execute(task, binding);
    EXPECT_EQ(result.status, ak::ExecutionStatus::kFailed);
    EXPECT_TRUE(result.IsFailure());
    EXPECT_FALSE(result.IsSuccess());
}

// ============================================================
// Retryable semantics
// ============================================================
TEST(ExecutorTest, CompletedIsNotRetryable) {
    Executor executor;
    auto task = CreateValidTask(ak::TaskID(1), "t");
    auto binding = MakeBinding("t");

    auto result = executor.Execute(task, binding);
    EXPECT_FALSE(result.retryable);
}

TEST(ExecutorTest, FailedByValidationIsNotRetryable) {
    Executor executor;
    auto task = CreateValidTask(ak::TaskID(2), "x");
    auto binding = MakeBinding("");

    auto result = executor.Execute(task, binding);
    EXPECT_EQ(result.status, ak::ExecutionStatus::kFailed);
    EXPECT_FALSE(result.retryable);
}

// ============================================================
// Deterministic Execution
// ============================================================
TEST(ExecutorTest, SameInputProducesSameStatus) {
    Executor ex1, ex2;
    auto t1 = CreateValidTask(ak::TaskID(10), "det.op");
    auto t2 = CreateValidTask(ak::TaskID(10), "det.op");

    auto r1 = ex1.Execute(t1, MakeBinding("det.op"));
    auto r2 = ex2.Execute(t2, MakeBinding("det.op"));

    EXPECT_EQ(r1.status, r2.status);
    EXPECT_EQ(r1.IsSuccess(), r2.IsSuccess());
    EXPECT_EQ(r1.output.has_value(), r2.output.has_value());
}

// ============================================================
// Runtime Integration — invoke through Runtime::GetExecutor()
// ============================================================
TEST(ExecutorTest, RuntimeProvidesExecutorReference) {
    Runtime runtime;
    auto& executor = runtime.GetExecutor();
    auto task = CreateValidTask(ak::TaskID(99), "runtime.integration");

    auto result = executor.Execute(task, MakeBinding("runtime.integration"));
    EXPECT_EQ(result.status, ak::ExecutionStatus::kCompleted);
    EXPECT_TRUE(result.IsSuccess());
}

// ============================================================
// Boundary Conditions
// ============================================================
TEST(ExecutorTest, EmptyBindingProducesFailedResult) {
    Executor executor;
    auto task = CreateValidTask(ak::TaskID(3), "irrelevant");
    ak::ExecutionBinding emptyBinding;

    auto result = executor.Execute(task, emptyBinding);
    EXPECT_EQ(result.status, ak::ExecutionStatus::kFailed);
    EXPECT_FALSE(result.output.has_value());
}

TEST(ExecutorTest, SpecialCapabilityNameSucceeds) {
    Executor executor;
    auto task = CreateValidTask(ak::TaskID(5), "ns.sub.cap.v2");

    auto result = executor.Execute(task, MakeBinding("ns.sub.cap.v2"));
    EXPECT_EQ(result.status, ak::ExecutionStatus::kCompleted);
    EXPECT_TRUE(result.output.has_value());
}

// ============================================================
// Integration: Resolver -> Executor flow (FIX0004)
// ============================================================
TEST(ExecutorTest, ResolverAndExecutorWorkflow) {
    CapabilityResolver resolver;
    CapabilityResolverTestAccess::Register(resolver, "llm.chat", "openai");

    auto desc = MakeDescriptor("llm.chat");
    auto binding = resolver.Resolve(desc);

    // AK0033: Resolve returns CapabilityBinding with providerName.
    EXPECT_EQ(binding.providerName, "openai");

    // Executor still uses ExecutionBinding (AK0036 canonical type).
    ak::CapabilityIdentifier cid;
    cid.name = "llm.chat";
    cid.provider = binding.providerName;
    cid.version = 1;

    ak::ExecutionBinding execBinding;
    execBinding.capabilityID = cid;
    execBinding.status = ak::BindingStatus::kReady;
    execBinding.capabilityVersion = {1, 0, 0};
    // C1: deterministic real invoker for the resolved capability
    // (a binding without an invoker fails deterministically).
    execBinding.payload = "payload:llm.chat";
    execBinding.invoker = [](const std::string& payload) {
        return "llm-output:" + payload;
    };

    // Now execute using the resolved binding.
    Executor executor;
    auto task = CreateValidTask(ak::TaskID(10), "llm.chat");
    auto result = executor.Execute(task, execBinding);

    EXPECT_EQ(result.status, ak::ExecutionStatus::kCompleted);
    EXPECT_TRUE(result.output.has_value());
}

// ============================================================
// Scope Compliance — Executor produces only ExecutionResult
// ============================================================
TEST(ExecutorTest, ExecuteProducesOnlyExecutionResult) {
    Executor executor;
    auto task = CreateValidTask(ak::TaskID(1), "t");

    auto result = executor.Execute(task, MakeBinding("t"));
    EXPECT_TRUE(result.IsSuccess());
    EXPECT_TRUE(result.output.has_value());
}

}  // namespace
}  // namespace ak::runtime
