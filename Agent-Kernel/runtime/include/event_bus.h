// ============================================================
// P0R0005 — Runtime Event Bus
// ============================================================
// Concrete implementation of the canonical Runtime Event Bus
// per AK0034 (Runtime Event Bus Specification).
//
// Public API (AK0034 §6.2):
//   EventBus();
//   ~EventBus();
//   void Publish(const RuntimeEvent& event);
//
// Subscriber management (Subscribe, Unsubscribe,
// ClearSubscriptions, IsSubscribed) and statistics are
// internal to the EventBus implementation and do NOT form
// part of the Runtime architectural contract (AK0034 §6.2).
// They are exposed on the concrete class for Runtime
// integration and verification purposes.
//
// Responsibilities (P0R0005 §2.11):
// - Publish Runtime Events
// - Register Subscribers
// - Dispatch Runtime Events
// - Preserve Event Immutability
//
// NON-responsibilities:
// - Does NOT execute Tasks (Executor — P0R0003)
// - Does NOT resolve Capabilities (Resolver — P0R0004)
// - Does NOT schedule Tasks (Scheduler — P0R0002)
// - Does NOT manage Runtime lifecycle
// - Does NOT modify Runtime state
//
// Revision 2 constraints (P0R0005 §2.12):
// - Fully synchronous, single-threaded
// - No worker threads, futures, promises, coroutines
// - No distributed messaging or persistent queues
//
// Conforms to AK0034 (Runtime Event Bus Specification).
// ============================================================

#pragma once

#include <cstdint>
#include <functional>
#include <string>
#include <unordered_map>
#include <vector>

#include <runtime_event.h>

namespace ak::runtime {

// ============================================================
// EventCallback — subscriber callback type (AK0034 §11.1)
// ============================================================
using EventCallback = std::function<void(const ak::RuntimeEvent&)>;

// ============================================================
// SubscriptionToken — unique subscription identifier (AK0034 §8.3)
// ============================================================
using SubscriptionToken = std::uint64_t;

// ============================================================
// EventBus — Runtime event publication component (P0R0005)
// ============================================================
class EventBus {
public:
    EventBus();
    ~EventBus();

    EventBus(const EventBus&) = delete;
    EventBus& operator=(const EventBus&) = delete;
    EventBus(EventBus&&) = delete;
    EventBus& operator=(EventBus&&) = delete;

    // ---- AK0034 §6.2 — Canonical public API ----
    //
    // Publish an immutable RuntimeEvent. Dispatches the event
    // to all subscribers registered for the event type.
    // Deterministic; synchronous; never throws.
    void Publish(const ak::RuntimeEvent& event);

    // ---- Internal subscription management (AK0034 §8-9) ----

    // Register a subscriber callback for a Runtime event type.
    // Returns a unique SubscriptionToken, or 0 when the callback
    // is invalid (no target).
    SubscriptionToken Subscribe(ak::RuntimeEventType type,
                                EventCallback callback);

    // Remove a subscription. Returns true if the token existed.
    bool Unsubscribe(SubscriptionToken token);

    // Remove all active subscriptions.
    void ClearSubscriptions();

    // Returns whether a subscription token is currently active.
    [[nodiscard]] bool IsSubscribed(SubscriptionToken token) const;

    // Number of subscribers registered for a given event type.
    [[nodiscard]] std::size_t GetSubscriberCount(
        ak::RuntimeEventType type) const;

    // ---- Internal diagnostics (AK0034 §12) ----

    // Total number of events successfully published.
    [[nodiscard]] std::uint64_t GetPublishedCount() const noexcept;

    // Number of active subscriptions.
    [[nodiscard]] std::size_t GetTotalSubscriberCount() const noexcept;

private:
    struct Subscription {
        ak::RuntimeEventType type;
        EventCallback callback;
    };

    // Publish event to the given subscriber callback, isolating
    // subscriber exceptions (AK0034 §18.4: subscriber failures
    // shall be isolated; one failing subscriber shall not
    // invalidate delivery to other subscribers).
    static void DispatchToSubscriber(
        const EventCallback& callback,
        const ak::RuntimeEvent& event) noexcept;

    // Deterministic subscription registry.
    // token -> subscription
    std::unordered_map<SubscriptionToken, Subscription> subscriptions_;
    // event type -> ordered list of subscription tokens
    // (registration order preserved for deterministic dispatch)
    std::unordered_map<ak::RuntimeEventType,
                       std::vector<SubscriptionToken>> typeIndex_;

    // Next subscription token (monotonically increasing).
    SubscriptionToken nextToken_ = 1;

    // Next publication EventID (AK0034 §2.4). Monotonically
    // increasing: every publication instance receives a unique
    // EventID, even for identical payloads.
    std::uint64_t nextEventID_ = 1;

    // Diagnostic counters (AK0034 §12 — internal only).
    std::uint64_t publishedCount_ = 0;
};

}  // namespace ak::runtime
