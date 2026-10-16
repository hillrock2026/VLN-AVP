#include <gtest/gtest.h>

#include <event_bus.h>
#include <runtime_event.h>
#include <runtime.h>
#include <agent_kernel/session.hpp>
#include <agent_kernel/session/session_configuration.hpp>
#include <agent_kernel/session/session_builder.hpp>
#include <memory>
#include <type_traits>

namespace ak::runtime {
namespace {

// Helper: create a valid RuntimeEvent.
ak::RuntimeEvent MakeEvent(ak::RuntimeEventType type,
                           const std::string& message = "event") {
    ak::RuntimeEvent event;
    event.type = type;
    event.taskID = ak::TaskID(1);
    event.workflowID = ak::WorkflowID(2);
    event.sessionID = ak::SessionID(3);
    event.message = message;
    return event;
}

// Helper: create a ready session.
std::unique_ptr<ak::Session> CreateReadySession() {
    auto session = ak::SessionBuilder()
        .WithID(ak::SessionID(1))
        .WithName("EventBus_Test_Session")
        .WithMaxWorkflows(0)
        .Build();
    session->Initialize();
    session->Activate();
    return session;
}

// ============================================================
// Construction
// ============================================================
TEST(EventBusTest, ConstructionSucceeds) {
    EventBus bus;
    EXPECT_EQ(bus.GetTotalSubscriberCount(), 0u);
    EXPECT_EQ(bus.GetPublishedCount(), 0u);
}

TEST(EventBusTest, DestructionIsSafe) {
    { EventBus bus; }
    SUCCEED();
}

// ============================================================
// Publish Event
// ============================================================
TEST(EventBusTest, PublishValidEventSucceeds) {
    EventBus bus;
    EXPECT_NO_THROW(bus.Publish(MakeEvent(ak::RuntimeEventType::kTaskStarted)));
    EXPECT_EQ(bus.GetPublishedCount(), 1u);
}

// ============================================================
// Subscriber Notification
// ============================================================
TEST(EventBusTest, RegisteredSubscriberReceivesEvent) {
    EventBus bus;
    bool received = false;
    ak::RuntimeEvent receivedEvent;

    auto token = bus.Subscribe(ak::RuntimeEventType::kTaskCompleted,
        [&](const ak::RuntimeEvent& event) {
            received = true;
            receivedEvent = event;
        });

    EXPECT_NE(token, 0u);
    bus.Publish(MakeEvent(ak::RuntimeEventType::kTaskCompleted, "done"));

    EXPECT_TRUE(received);
    EXPECT_EQ(receivedEvent.message, "done");
}

// ============================================================
// Event Immutability
// ============================================================
TEST(EventBusTest, PublishedEventRemainsUnchanged) {
    EventBus bus;
    std::string messageSeen;

    bus.Subscribe(ak::RuntimeEventType::kTaskStarted,
        [&](const ak::RuntimeEvent& event) {
            messageSeen = event.message;
        });

    auto event = MakeEvent(ak::RuntimeEventType::kTaskStarted, "original");
    bus.Publish(event);

    // Event must remain unchanged after dispatch.
    EXPECT_EQ(event.message, "original");
    EXPECT_EQ(event.type, ak::RuntimeEventType::kTaskStarted);
    EXPECT_EQ(messageSeen, "original");
}

// ============================================================
// Determinism
// ============================================================
TEST(EventBusTest, RepeatedPublicationIsDeterministic) {
    EventBus bus;
    std::vector<std::string> order1, order2;

    bus.Subscribe(ak::RuntimeEventType::kWorkflowStarted,
        [&](const ak::RuntimeEvent&) { order1.push_back("a"); });
    bus.Subscribe(ak::RuntimeEventType::kWorkflowStarted,
        [&](const ak::RuntimeEvent&) { order1.push_back("b"); });
    bus.Subscribe(ak::RuntimeEventType::kWorkflowStarted,
        [&](const ak::RuntimeEvent&) { order1.push_back("c"); });

    auto event = MakeEvent(ak::RuntimeEventType::kWorkflowStarted);
    bus.Publish(event);
    bus.Publish(event);

    // Registration order must be preserved on every publication.
    EXPECT_EQ(order1, std::vector<std::string>({"a", "b", "c", "a", "b", "c"}));
}

// ============================================================
// Subscriber Type Routing
// ============================================================
TEST(EventBusTest, SubscribersOnlyReceiveMatchingType) {
    EventBus bus;
    int taskCount = 0;
    int workflowCount = 0;

    bus.Subscribe(ak::RuntimeEventType::kTaskStarted,
        [&](const ak::RuntimeEvent&) { ++taskCount; });
    bus.Subscribe(ak::RuntimeEventType::kWorkflowStarted,
        [&](const ak::RuntimeEvent&) { ++workflowCount; });

    bus.Publish(MakeEvent(ak::RuntimeEventType::kTaskStarted));
    bus.Publish(MakeEvent(ak::RuntimeEventType::kWorkflowStarted));
    bus.Publish(MakeEvent(ak::RuntimeEventType::kTaskFailed));

    EXPECT_EQ(taskCount, 1);      // kTaskStarted only
    EXPECT_EQ(workflowCount, 1);  // kWorkflowStarted only
}

// ============================================================
// Runtime Integration
// ============================================================
TEST(EventBusTest, RuntimeProvidesEventBusReference) {
    Runtime runtime;
    auto& bus = runtime.GetEventBus();

    bool received = false;
    bus.Subscribe(ak::RuntimeEventType::kSessionStarted,
        [&](const ak::RuntimeEvent&) { received = true; });

    bus.Publish(MakeEvent(ak::RuntimeEventType::kSessionStarted, "run"));
    EXPECT_TRUE(received);
}

TEST(EventBusTest, RuntimeRunPublishesSessionEvents) {
    Runtime runtime;
    auto session = CreateReadySession();

    std::vector<std::string> events;
    auto& bus = runtime.GetEventBus();
    bus.Subscribe(ak::RuntimeEventType::kSessionStarted,
        [&](const ak::RuntimeEvent& e) { events.push_back(e.message); });
    bus.Subscribe(ak::RuntimeEventType::kSessionCompleted,
        [&](const ak::RuntimeEvent& e) { events.push_back(e.message); });

    auto result = runtime.Run(*session);

    EXPECT_EQ(result.status, RuntimeStatus::kCompleted);
    ASSERT_EQ(events.size(), 2u);
    EXPECT_EQ(events[0], "session started");
    EXPECT_EQ(events[1], "session completed");
}

// ============================================================
// Negative — Publish Invalid RuntimeEvent
// ============================================================
TEST(EventBusTest, PublishInvalidEventDoesNotNotifySubscribers) {
    EventBus bus;
    int notified = 0;

    bus.Subscribe(ak::RuntimeEventType::kTaskStarted,
        [&](const ak::RuntimeEvent&) { ++notified; });

    // Invalid: unrecognized type value (out of enum range).
    ak::RuntimeEvent invalid;
    invalid.type = static_cast<ak::RuntimeEventType>(0xFF);
    invalid.message = "invalid";
    bus.Publish(invalid);

    // Deterministic outcome: no subscribers notified, no state change.
    EXPECT_EQ(notified, 0);
    EXPECT_EQ(bus.GetPublishedCount(), 0u);
    EXPECT_EQ(bus.GetTotalSubscriberCount(), 1u);
}

TEST(EventBusTest, PublishInvalidEventWithEmptyMessageIsIgnored) {
    EventBus bus;
    int notified = 0;
    bus.Subscribe(ak::RuntimeEventType::kTaskStarted,
        [&](const ak::RuntimeEvent&) { ++notified; });

    // Invalid: recognized type but empty message.
    bus.Publish(MakeEvent(ak::RuntimeEventType::kTaskStarted, ""));

    EXPECT_EQ(notified, 0);
    EXPECT_EQ(bus.GetPublishedCount(), 0u);
}

// ============================================================
// Negative — Publish With No Registered Subscribers
// ============================================================
TEST(EventBusTest, PublishWithNoSubscribersCompletesWithoutSideEffects) {
    EventBus bus;
    EXPECT_NO_THROW(bus.Publish(MakeEvent(ak::RuntimeEventType::kTaskFailed)));
    EXPECT_EQ(bus.GetPublishedCount(), 1u);
    EXPECT_EQ(bus.GetTotalSubscriberCount(), 0u);
}

// ============================================================
// Negative — Duplicate Subscriber Registration
// ============================================================
TEST(EventBusTest, DuplicateRegistrationGetsDistinctTokens) {
    EventBus bus;
    int calls = 0;
    EventCallback cb = [&](const ak::RuntimeEvent&) { ++calls; };

    auto t1 = bus.Subscribe(ak::RuntimeEventType::kTaskStarted, cb);
    auto t2 = bus.Subscribe(ak::RuntimeEventType::kTaskStarted, cb);

    EXPECT_NE(t1, 0u);
    EXPECT_NE(t2, 0u);
    EXPECT_NE(t1, t2);
    EXPECT_EQ(bus.GetSubscriberCount(ak::RuntimeEventType::kTaskStarted), 2u);

    bus.Publish(MakeEvent(ak::RuntimeEventType::kTaskStarted));
    EXPECT_EQ(calls, 2);  // both registrations notified
}

// ============================================================
// Negative — Invalid Subscriber Registration
// ============================================================
TEST(EventBusTest, InvalidSubscriberRegistrationIsRejected) {
    EventBus bus;

    // Empty callback (no target) is rejected: token 0.
    auto token = bus.Subscribe(ak::RuntimeEventType::kTaskStarted, {});
    EXPECT_EQ(token, 0u);
    EXPECT_EQ(bus.GetTotalSubscriberCount(), 0u);
}

TEST(EventBusTest, InvalidTypeSubscriptionIsRejected) {
    EventBus bus;
    EventCallback cb = [](const ak::RuntimeEvent&) {};

    auto token = bus.Subscribe(static_cast<ak::RuntimeEventType>(0xFF), cb);
    EXPECT_EQ(token, 0u);
    EXPECT_EQ(bus.GetTotalSubscriberCount(), 0u);
}

// ============================================================
// Negative — Publication Failure Isolation
// ============================================================
TEST(EventBusTest, PublicationFailureDoesNotAffectSubsequentPublishes) {
    EventBus bus;
    int successCalls = 0;

    // First subscriber always throws.
    bus.Subscribe(ak::RuntimeEventType::kTaskStarted,
        [](const ak::RuntimeEvent&) { throw std::runtime_error("boom"); });
    // Second subscriber records calls.
    bus.Subscribe(ak::RuntimeEventType::kTaskStarted,
        [&](const ak::RuntimeEvent&) { ++successCalls; });

    // First publication: exception isolated, other subscriber notified.
    EXPECT_NO_THROW(bus.Publish(MakeEvent(ak::RuntimeEventType::kTaskStarted)));
    EXPECT_EQ(successCalls, 1);

    // Subsequent publication still works.
    EXPECT_NO_THROW(bus.Publish(MakeEvent(ak::RuntimeEventType::kTaskStarted)));
    EXPECT_EQ(successCalls, 2);
    EXPECT_EQ(bus.GetPublishedCount(), 2u);
}

// ============================================================
// Negative — Subscriber Exception Isolation
// ============================================================
TEST(EventBusTest, SubscriberExceptionDoesNotBlockOtherSubscribers) {
    EventBus bus;
    std::vector<std::string> notified;

    bus.Subscribe(ak::RuntimeEventType::kTaskStarted,
        [](const ak::RuntimeEvent&) { throw std::runtime_error("failing"); });
    bus.Subscribe(ak::RuntimeEventType::kTaskStarted,
        [&](const ak::RuntimeEvent&) { notified.push_back("a"); });
    bus.Subscribe(ak::RuntimeEventType::kTaskStarted,
        [&](const ak::RuntimeEvent&) { notified.push_back("b"); });

    EXPECT_NO_THROW(bus.Publish(MakeEvent(ak::RuntimeEventType::kTaskStarted)));

    // All non-failing subscribers still receive the event.
    EXPECT_EQ(notified, std::vector<std::string>({"a", "b"}));
}

// ============================================================
// Negative — Runtime State Unchanged After Publication Failure
// ============================================================
TEST(EventBusTest, RuntimeStateUnchangedAfterSubscriberFailure) {
    Runtime runtime;
    auto& bus = runtime.GetEventBus();

    bus.Subscribe(ak::RuntimeEventType::kSessionStarted,
        [](const ak::RuntimeEvent&) { throw std::runtime_error("boom"); });

    auto session = CreateReadySession();
    auto result = runtime.Run(*session);

    // Runtime execution completes normally despite subscriber failure.
    EXPECT_EQ(result.status, RuntimeStatus::kCompleted);
    EXPECT_TRUE(result.IsSuccess());
    EXPECT_TRUE(runtime.IsRunning());
}

// ============================================================
// Unsubscribe / ClearSubscriptions
// ============================================================
TEST(EventBusTest, UnsubscribeRemovesSubscription) {
    EventBus bus;
    int calls = 0;
    auto token = bus.Subscribe(ak::RuntimeEventType::kTaskStarted,
        [&](const ak::RuntimeEvent&) { ++calls; });

    EXPECT_TRUE(bus.IsSubscribed(token));
    EXPECT_TRUE(bus.Unsubscribe(token));
    EXPECT_FALSE(bus.IsSubscribed(token));
    EXPECT_FALSE(bus.Unsubscribe(token));  // already removed

    bus.Publish(MakeEvent(ak::RuntimeEventType::kTaskStarted));
    EXPECT_EQ(calls, 0);
}

TEST(EventBusTest, ClearSubscriptionsRemovesAll) {
    EventBus bus;
    bus.Subscribe(ak::RuntimeEventType::kTaskStarted,
        [](const ak::RuntimeEvent&) {});
    bus.Subscribe(ak::RuntimeEventType::kTaskFailed,
        [](const ak::RuntimeEvent&) {});

    EXPECT_EQ(bus.GetTotalSubscriberCount(), 2u);
    bus.ClearSubscriptions();
    EXPECT_EQ(bus.GetTotalSubscriberCount(), 0u);
}

// ============================================================
// Scope Compliance — EventBus performs no scheduling/execution
// ============================================================
namespace scope_compliance_detail {

// Compile-time member-existence detection (CAP5-P002 / SIR5-MIN-001):
// each trait is true only when the inspected type exposes a member
// with the given name. Used to prove, at compile time, that the
// EventBus surface exposes none of the Scheduler / Executor /
// CapabilityResolver / Runtime lifecycle entry points
// (P0R0005 §2.11 NON-responsibilities).

template <typename T, typename = void>
struct HasMemberSchedule : std::false_type {};
template <typename T>
struct HasMemberSchedule<T, std::void_t<decltype(&T::Schedule)>>
    : std::true_type {};

template <typename T, typename = void>
struct HasMemberExecute : std::false_type {};
template <typename T>
struct HasMemberExecute<T, std::void_t<decltype(&T::Execute)>>
    : std::true_type {};

template <typename T, typename = void>
struct HasMemberResolve : std::false_type {};
template <typename T>
struct HasMemberResolve<T, std::void_t<decltype(&T::Resolve)>>
    : std::true_type {};

template <typename T, typename = void>
struct HasMemberRegister : std::false_type {};
template <typename T>
struct HasMemberRegister<T, std::void_t<decltype(&T::Register)>>
    : std::true_type {};

template <typename T, typename = void>
struct HasMemberUnregister : std::false_type {};
template <typename T>
struct HasMemberUnregister<T, std::void_t<decltype(&T::Unregister)>>
    : std::true_type {};

template <typename T, typename = void>
struct HasMemberInitialize : std::false_type {};
template <typename T>
struct HasMemberInitialize<T, std::void_t<decltype(&T::Initialize)>>
    : std::true_type {};

template <typename T, typename = void>
struct HasMemberShutdown : std::false_type {};
template <typename T>
struct HasMemberShutdown<T, std::void_t<decltype(&T::Shutdown)>>
    : std::true_type {};

template <typename T, typename = void>
struct HasMemberRun : std::false_type {};
template <typename T>
struct HasMemberRun<T, std::void_t<decltype(&T::Run)>>
    : std::true_type {};

}  // namespace scope_compliance_detail

// ---- Compile-time scope compliance evidence (P0R0005 §2.11) ----

// EventBus performs no scheduling (Scheduler — P0R0002).
static_assert(!scope_compliance_detail::HasMemberSchedule<EventBus>::value,
              "EventBus SHALL NOT expose scheduling operations");

// EventBus performs no execution (Executor — P0R0003).
static_assert(!scope_compliance_detail::HasMemberExecute<EventBus>::value,
              "EventBus SHALL NOT expose task execution operations");

// EventBus performs no capability resolution (Resolver — P0R0004).
static_assert(!scope_compliance_detail::HasMemberResolve<EventBus>::value,
              "EventBus SHALL NOT expose capability resolution");
static_assert(!scope_compliance_detail::HasMemberRegister<EventBus>::value,
              "EventBus SHALL NOT expose capability registration");
static_assert(!scope_compliance_detail::HasMemberUnregister<EventBus>::value,
              "EventBus SHALL NOT expose capability unregistration");

// EventBus does not manage the Runtime lifecycle.
static_assert(!scope_compliance_detail::HasMemberInitialize<EventBus>::value,
              "EventBus SHALL NOT expose lifecycle initialization");
static_assert(!scope_compliance_detail::HasMemberShutdown<EventBus>::value,
              "EventBus SHALL NOT expose lifecycle shutdown");
static_assert(!scope_compliance_detail::HasMemberRun<EventBus>::value,
              "EventBus SHALL NOT expose Runtime execution");

// ---- Interface conformance evidence (AK0034 §6.2) ----

// Publish(const RuntimeEvent&) is the canonical publication API and
// SHALL return void.
static_assert(
    std::is_same_v<decltype(std::declval<EventBus&>().Publish(
                       std::declval<const ak::RuntimeEvent&>())),
                   void>,
    "EventBus::Publish SHALL accept const RuntimeEvent& and return void");

TEST(EventBusTest, EventBusExposesNoSchedulingExecutionOrResolutionAPIs) {
    EventBus bus;
    // Compile-time evidence above demonstrates that the EventBus
    // public surface contains no Scheduler / Executor / Resolver /
    // lifecycle entry points (P0R0005 §2.11). This test documents
    // the verified scope: publication and subscriber management only.
    EXPECT_EQ(bus.GetTotalSubscriberCount(), 0u);
    EXPECT_NO_THROW(bus.Publish(MakeEvent(ak::RuntimeEventType::kTaskStarted)));
    EXPECT_EQ(bus.GetPublishedCount(), 1u);
}

TEST(EventBusTest, EventBusOperatesSynchronouslyWithoutThreads) {
    EventBus bus;
    int order = 0;
    int lastSeen = 0;

    bus.Subscribe(ak::RuntimeEventType::kTaskStarted,
        [&](const ak::RuntimeEvent&) {
            lastSeen = ++order;  // executes synchronously in order
        });

    bus.Publish(MakeEvent(ak::RuntimeEventType::kTaskStarted));
    EXPECT_EQ(lastSeen, 1);  // dispatch completed before Publish() returned
}


// ============================================================
// Event Publication Metadata (CAP0006-001)
// ============================================================
TEST(EventBusTest, PublishedEventReceivesEventIDAndTimestamp) {
    EventBus bus;
    bool received = false;
    ak::RuntimeEvent receivedEvent;

    bus.Subscribe(ak::RuntimeEventType::kTaskStarted,
        [&](const ak::RuntimeEvent& event) {
            received = true;
            receivedEvent = event;
        });

    bus.Publish(MakeEvent(ak::RuntimeEventType::kTaskStarted, "meta"));

    ASSERT_TRUE(received);
    // AK0034 2.4 / 2.5: every publication carries a unique EventID
    // and the timestamp at which the event entered the Event Bus.
    EXPECT_NE(receivedEvent.eventID, ak::EventID{0});
    EXPECT_NE(receivedEvent.timestamp, ak::Timestamp{0});
}

TEST(EventBusTest, DistinctPublicationsReceiveDistinctEventIDs) {
    EventBus bus;
    std::vector<ak::EventID> ids;

    bus.Subscribe(ak::RuntimeEventType::kTaskStarted,
        [&](const ak::RuntimeEvent& event) { ids.push_back(event.eventID); });

    // Identical payload published twice: each publication instance
    // must receive a distinct EventID (AK0034 2.4).
    auto event = MakeEvent(ak::RuntimeEventType::kTaskStarted);
    bus.Publish(event);
    bus.Publish(event);

    ASSERT_EQ(ids.size(), 2u);
    EXPECT_NE(ids[0], ak::EventID{0});
    EXPECT_NE(ids[1], ak::EventID{0});
    EXPECT_NE(ids[0], ids[1]);
}

TEST(EventBusTest, TimestampIsSetAtPublicationAndNeverChanges) {
    EventBus bus;
    std::vector<ak::Timestamp> timestamps;

    bus.Subscribe(ak::RuntimeEventType::kTaskStarted,
        [&](const ak::RuntimeEvent& event) {
            timestamps.push_back(event.timestamp);
        });

    auto event = MakeEvent(ak::RuntimeEventType::kTaskStarted);
    bus.Publish(event);
    bus.Publish(event);

    ASSERT_EQ(timestamps.size(), 2u);
    // AK0034 2.5: timestamps are recorded when events enter the
    // Event Bus (monotonic source) and never change afterwards.
    EXPECT_NE(timestamps[0], ak::Timestamp{0});
    EXPECT_NE(timestamps[1], ak::Timestamp{0});
    EXPECT_GE(timestamps[1], timestamps[0]);
}

TEST(EventBusTest, RuntimeEventValidationVerifiesEventIDAndTimestamp) {
    ak::RuntimeEvent event;
    event.type = ak::RuntimeEventType::kTaskStarted;
    event.taskID = ak::TaskID(1);
    event.workflowID = ak::WorkflowID(2);
    event.sessionID = ak::SessionID(3);
    event.message = "valid";

    // Missing publication metadata is invalid (AK0034 14.3).
    EXPECT_FALSE(IsValidRuntimeEvent(event));

    event.eventID = ak::EventID{7};
    event.timestamp = ak::Timestamp{100};
    EXPECT_TRUE(IsValidRuntimeEvent(event));

    // EventID validity: a zero EventID is not a valid publication id.
    event.eventID = ak::EventID{0};
    EXPECT_FALSE(IsValidRuntimeEvent(event));
}

TEST(EventBusTest, RuntimeRunPublishesEventsWithMetadata) {
    Runtime runtime;
    auto session = CreateReadySession();

    bool received = false;
    ak::EventID eventID = 0;
    ak::Timestamp timestamp = 0;
    runtime.GetEventBus().Subscribe(ak::RuntimeEventType::kSessionStarted,
        [&](const ak::RuntimeEvent& event) {
            received = true;
            eventID = event.eventID;
            timestamp = event.timestamp;
        });

    RuntimeResult result = runtime.Run(*session);

    EXPECT_TRUE(result.IsSuccess());
    ASSERT_TRUE(received);
    // Runtime-published lifecycle events carry the full metadata
    // contract defined by AK0034 10.2.
    EXPECT_NE(eventID, ak::EventID{0});
    EXPECT_NE(timestamp, ak::Timestamp{0});
}

}  // namespace
}  // namespace ak::runtime
