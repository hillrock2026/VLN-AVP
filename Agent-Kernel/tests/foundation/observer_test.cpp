// ============================================================
// observer_test.cpp - P1-IS001 observation boundary tests
// ============================================================
// Verifies:
// - ObserverRegistry provides owner-scoped attach/detach/notify.
// - Observation is technical, not coordination: it exposes no
//   event-bus API (publish/subscribe/topics) and no Runtime
//   event semantics.
// - Observers do not become the Runtime Event Bus.
// ============================================================

#include <agent_kernel/foundation/kernel_observer.hpp>

#include <gtest/gtest.h>

#include <memory>
#include <string>
#include <type_traits>
#include <utility>

namespace ak {
namespace {

// ------------------------------------------------------------
// SFINAE member detectors
// ------------------------------------------------------------
template <typename T, typename = void>
struct HasPublish : std::false_type {};
template <typename T>
struct HasPublish<T, std::void_t<decltype(std::declval<T&>().Publish(
                         std::declval<const char*>()))>>
    : std::true_type {};

template <typename T, typename = void>
struct HasSubscribe : std::false_type {};
template <typename T>
struct HasSubscribe<T, std::void_t<decltype(std::declval<T&>().Subscribe(
                           std::declval<const char*>()))>>
    : std::true_type {};

template <typename T, typename = void>
struct HasPost : std::false_type {};
template <typename T>
struct HasPost<T, std::void_t<decltype(std::declval<T&>().Post(
                      std::declval<const char*>()))>>
    : std::true_type {};

// ------------------------------------------------------------
// Test observer + test subject
// ------------------------------------------------------------
class RecordingObserver : public KernelObserver {
public:
    void OnStateChanged(uint64_t objectId, uint8_t newState) override {
        ++stateChanges;
        lastId = objectId;
        lastState = newState;
    }

    void OnError(uint64_t objectId, uint8_t state,
                 const char* message) override {
        ++errors;
        lastId = objectId;
        lastState = state;
        lastMessage = message;
    }

    int stateChanges = 0;
    int errors = 0;
    uint64_t lastId = 0;
    uint8_t lastState = 0;
    const char* lastMessage = "";
};

// Owner-scoped subject that composes ObserverRegistry and
// triggers notifications through its own methods only.
class TestSubject : public ObserverRegistry {
public:
    using ObserverRegistry::NotifyError;
    using ObserverRegistry::NotifyStateChange;
};

TEST(ObserverRegistry, AttachNotifyDetachIsOwnerScoped) {
    TestSubject subject;
    auto observer = std::make_shared<RecordingObserver>();

    subject.Attach(observer);
    subject.NotifyStateChange(10, 3);

    EXPECT_EQ(observer->stateChanges, 1);
    EXPECT_EQ(observer->lastId, 10);
    EXPECT_EQ(observer->lastState, 3);

    subject.Detach(observer.get());
    subject.NotifyStateChange(11, 4);

    EXPECT_EQ(observer->stateChanges, 1);
}

TEST(ObserverRegistry, NotifyErrorReachesObservers) {
    TestSubject subject;
    auto observer = std::make_shared<RecordingObserver>();

    subject.Attach(observer);
    subject.NotifyError(5, 2, "failed");

    EXPECT_EQ(observer->errors, 1);
    EXPECT_EQ(observer->lastId, 5);
    EXPECT_EQ(observer->lastState, 2);
    EXPECT_EQ(std::string(observer->lastMessage), "failed");
}

TEST(ObserverRegistry, DoesNotHoldObserversAlive) {
    TestSubject subject;
    auto survivor = std::make_shared<RecordingObserver>();
    subject.Attach(survivor);
    {
        auto transient = std::make_shared<RecordingObserver>();
        subject.Attach(transient);
    }
    // The registry stores weak references; a destroyed observer
    // is skipped on the next notification while survivors
    // continue to receive it.
    subject.NotifyStateChange(1, 1);
    EXPECT_EQ(survivor->stateChanges, 1);
}

TEST(ObserverRegistry, IsNotAnEventBus) {
    // Foundation observation is not Runtime event publication:
    // there is no publish/subscribe/topic API on the registry.
    static_assert(!HasPublish<ObserverRegistry>::value,
                  "ObserverRegistry must not expose Publish()");
    static_assert(!HasSubscribe<ObserverRegistry>::value,
                  "ObserverRegistry must not expose Subscribe()");
    static_assert(!HasPost<ObserverRegistry>::value,
                  "ObserverRegistry must not expose Post()");
}

}  // namespace
}  // namespace ak