// ============================================================
// memory_agent_contract_test.cpp - P1-IS003 Agent coordination
// ============================================================
// MEM-004 / MEM-010: Agent -> Memory is the authorized
// coordination direction; the Agent-facing contract requests
// lifecycle participation, inspects state, and invokes Memory
// Services; Memory gains no reverse coordination authority.
// ============================================================

#include <agent_kernel/memory/memory.hpp>
#include <agent_kernel/memory/memory_agent_contract.hpp>

#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <type_traits>

#include "test_doubles.hpp"

namespace ak::memory {
namespace {

// Negative API surface: the Agent-facing contract must not let
// Memory coordinate Agent, Context, Planner, or Tool.
template <typename T, typename = void>
struct HasInvokeAgent : std::false_type {};
template <typename T>
struct HasInvokeAgent<T, std::void_t<decltype(std::declval<T&>().InvokeAgent())>>
    : std::true_type {};

template <typename T, typename = void>
struct HasCoordinateContext : std::false_type {};
template <typename T>
struct HasCoordinateContext<T, std::void_t<decltype(std::declval<T&>().CoordinateContext())>>
    : std::true_type {};

TEST(MemoryAgentContract, ContractNameIsMemory) {
    Memory memory(MakeMemoryIdentity(1));
    EXPECT_EQ(std::string(memory.AgentContract().ContractName()), "Memory");
}

TEST(MemoryAgentContract, RequestsLifecycleParticipation) {
    Memory memory(MakeMemoryIdentity(2));

    EXPECT_TRUE(memory.AgentContract()
                    .RequestLifecycleParticipation(
                        MemoryLifecycleParticipation::kInitialize)
                    .IsSuccess());
    EXPECT_EQ(memory.AgentContract().InspectLifecycleState(),
              MemoryLifecycleState::kInitializing);

    EXPECT_TRUE(memory.AgentContract()
                    .RequestLifecycleParticipation(
                        MemoryLifecycleParticipation::kActivate)
                    .IsSuccess());
    EXPECT_EQ(memory.AgentContract().InspectLifecycleState(),
              MemoryLifecycleState::kActive);

    EXPECT_TRUE(memory.AgentContract()
                    .RequestLifecycleParticipation(
                        MemoryLifecycleParticipation::kSuspend)
                    .IsSuccess());
    EXPECT_EQ(memory.AgentContract().InspectLifecycleState(),
              MemoryLifecycleState::kSuspended);

    EXPECT_TRUE(memory.AgentContract()
                    .RequestLifecycleParticipation(
                        MemoryLifecycleParticipation::kResume)
                    .IsSuccess());
    EXPECT_EQ(memory.AgentContract().InspectLifecycleState(),
              MemoryLifecycleState::kActive);

    EXPECT_TRUE(memory.AgentContract()
                    .RequestLifecycleParticipation(
                        MemoryLifecycleParticipation::kTerminate)
                    .IsSuccess());
    EXPECT_EQ(memory.AgentContract().InspectLifecycleState(),
              MemoryLifecycleState::kTerminating);

    EXPECT_TRUE(memory.AgentContract()
                    .RequestLifecycleParticipation(
                        MemoryLifecycleParticipation::kDispose)
                    .IsSuccess());
    EXPECT_EQ(memory.AgentContract().InspectLifecycleState(),
              MemoryLifecycleState::kDisposed);
}

TEST(MemoryAgentContract, RejectsIllegalParticipationRequests) {
    Memory memory(MakeMemoryIdentity(3));

    // kActivate while Registered is illegal: Memory owns the
    // validation and rejects the request.
    const MemoryResult result = memory.AgentContract()
        .RequestLifecycleParticipation(MemoryLifecycleParticipation::kActivate);
    EXPECT_TRUE(result.IsRejected());
    EXPECT_EQ(memory.AgentContract().InspectLifecycleState(),
              MemoryLifecycleState::kRegistered);

    // kDispose while Active is illegal (Terminating required).
    ASSERT_TRUE(memory.AgentContract()
                    .RequestLifecycleParticipation(
                        MemoryLifecycleParticipation::kInitialize)
                    .IsSuccess());
    ASSERT_TRUE(memory.AgentContract()
                    .RequestLifecycleParticipation(
                        MemoryLifecycleParticipation::kActivate)
                    .IsSuccess());
    EXPECT_TRUE(memory.AgentContract()
                    .RequestLifecycleParticipation(
                        MemoryLifecycleParticipation::kDispose)
                    .IsRejected());
}

TEST(MemoryAgentContract, InspectsOperationalStateReadOnly) {
    Memory memory(MakeMemoryIdentity(4));
    EXPECT_EQ(memory.AgentContract().InspectOperationalState(),
              MemoryOperationalState::kUnavailable);

    // The Agent-facing path cannot mutate operational state; it
    // can only inspect and coordinate.
    ASSERT_TRUE(memory.InitializeLifecycle().IsSuccess());
    ASSERT_TRUE(memory.CompleteInitialization().IsSuccess());
    ASSERT_TRUE(memory.MarkReady().IsSuccess());
    ASSERT_TRUE(memory.MarkAvailable().IsSuccess());
    EXPECT_EQ(memory.AgentContract().InspectOperationalState(),
              MemoryOperationalState::kAvailable);
}

TEST(MemoryAgentContract, InvokesMemoryServicesThroughTheContract) {
    Memory memory(MakeMemoryIdentity(5));
    ASSERT_TRUE(test::ActivateAndMakeAvailable(memory));

    MemoryService& services = memory.AgentContract().Services();
    ASSERT_TRUE(services.CreateDomain(MakeMemoryDomainId(1), "d",
                                      test::MakeMetadata("d"))
                    .IsSuccess());
    ASSERT_TRUE(services.Retain(MakeMemoryEntryId(1), MakeMemoryDomainId(1),
                                MemoryObject(MakeMemoryObjectId(1), "payload",
                                             test::MakeMetadata("obj")))
                    .IsSuccess());

    const auto retrieved = memory.AgentContract().Services()
        .Retrieve(MakeMemoryEntryId(1));
    ASSERT_TRUE(retrieved.IsSuccess());
    EXPECT_EQ(retrieved.value.Content(), "payload");
}

TEST(MemoryAgentContract, ExposesNoReverseCoordination) {
    // The contract grants Memory no Agent invocation and no peer
    // coordination authority (P1-IS003 Chapter 12 / 21.2).
    static_assert(!HasInvokeAgent<MemoryAgentContract>::value,
                  "Memory must not invoke the Agent");
    static_assert(!HasCoordinateContext<MemoryAgentContract>::value,
                  "Memory must not coordinate Context");

}

}  // namespace
}  // namespace ak::memory