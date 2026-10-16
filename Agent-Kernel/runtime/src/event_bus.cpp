// ============================================================
// P0R0005 — Runtime Event Bus Implementation
// ============================================================
// Implements the AK0034 publication pipeline:
//   Receive RuntimeEvent → Validate Event → Determine
//   Subscribers → Dispatch Event → Return
//
// Revision 2: fully synchronous, single-threaded.
// Subscriber failures are isolated (AK0034 §18.4).
// Implementation exceptions never escape the public API
// (AK0034 §7.2 Exception Policy).

#include <event_bus.h>

#include <algorithm>
#include <chrono>
#include <exception>

namespace ak::runtime {

EventBus::EventBus() = default;

EventBus::~EventBus() = default;

// ============================================================
// AK0034 §7 — Publish
// ============================================================

void EventBus::Publish(const ak::RuntimeEvent& event) {
    // Stage 1 — Stamp publication metadata (AK0034 §2.4 / §2.5).
    // Every publication instance receives a unique EventID and the
    // timestamp at which the event entered the Event Bus. The
    // caller-supplied RuntimeEvent remains unchanged (AK0034 §7.2);
    // subscribers observe the stamped publication instance.
    ak::RuntimeEvent published = event;
    published.eventID = nextEventID_++;
    published.timestamp = static_cast<ak::Timestamp>(
        std::chrono::steady_clock::now().time_since_epoch().count());

    // Stage 2 — Validate Event (AK0034 §14.3).
    // Invalid events are ignored deterministically:
    // no subscribers are notified and no state is modified.
    if (!IsValidRuntimeEvent(published)) {
        return;
    }

    // Stage 3 — Determine Subscribers.
    // Look up the ordered subscriber list for the event type.
    auto it = typeIndex_.find(published.type);
    if (it == typeIndex_.end()) {
        // No subscribers registered for this type.
        // Publication completes without side effects.
        ++publishedCount_;
        return;
    }

    // Stage 4 — Dispatch Event.
    // Iterate in registration order for deterministic delivery.
    const auto& tokens = it->second;
    for (const auto token : tokens) {
        auto subIt = subscriptions_.find(token);
        if (subIt == subscriptions_.end()) {
            continue;  // Subscription was removed during publication.
        }
        // Isolate subscriber exceptions: one failing subscriber
        // must not prevent notification of other subscribers.
        DispatchToSubscriber(subIt->second.callback, published);
    }

    // Stage 5 — Return.
    ++publishedCount_;
}

// ============================================================
// AK0034 §8 — Subscribe (internal)
// ============================================================

SubscriptionToken EventBus::Subscribe(ak::RuntimeEventType type,
                                      EventCallback callback) {
    // Invalid subscriber registration: empty callback is rejected
    // deterministically by returning token 0 (never dispatched).
    if (!callback || !IsValidRuntimeEventType(type)) {
        return 0;
    }

    const SubscriptionToken token = nextToken_++;
    subscriptions_[token] = Subscription{type, std::move(callback)};
    typeIndex_[type].push_back(token);
    return token;
}

// ============================================================
// AK0034 §9 — Unsubscribe (internal)
// ============================================================

bool EventBus::Unsubscribe(SubscriptionToken token) {
    auto it = subscriptions_.find(token);
    if (it == subscriptions_.end()) {
        return false;
    }

    const auto type = it->second.type;
    subscriptions_.erase(it);

    // Remove token from the type index, preserving order of
    // the remaining subscriptions.
    auto typeIt = typeIndex_.find(type);
    if (typeIt != typeIndex_.end()) {
        auto& tokens = typeIt->second;
        tokens.erase(std::remove(tokens.begin(), tokens.end(), token),
                     tokens.end());
        if (tokens.empty()) {
            typeIndex_.erase(typeIt);
        }
    }

    return true;
}

void EventBus::ClearSubscriptions() {
    subscriptions_.clear();
    typeIndex_.clear();
}

bool EventBus::IsSubscribed(SubscriptionToken token) const {
    return subscriptions_.find(token) != subscriptions_.end();
}

std::size_t EventBus::GetSubscriberCount(
    ak::RuntimeEventType type) const {
    auto it = typeIndex_.find(type);
    if (it == typeIndex_.end()) {
        return 0;
    }
    return it->second.size();
}

// ============================================================
// AK0034 §12 — Diagnostics (internal)
// ============================================================

std::uint64_t EventBus::GetPublishedCount() const noexcept {
    return publishedCount_;
}

std::size_t EventBus::GetTotalSubscriberCount() const noexcept {
    return subscriptions_.size();
}

// ============================================================
// Private — Dispatch with subscriber exception isolation
// ============================================================

void EventBus::DispatchToSubscriber(
    const EventCallback& callback,
    const ak::RuntimeEvent& event) noexcept {
    try {
        callback(event);
    } catch (...) {
        // AK0034 §18.4: subscriber failures shall be isolated.
        // A failing subscriber must not terminate the Event Bus
        // nor prevent notification of other subscribers.
        // Exceptions never escape the public API (AK0034 §7.2).
    }
}

}  // namespace ak::runtime
