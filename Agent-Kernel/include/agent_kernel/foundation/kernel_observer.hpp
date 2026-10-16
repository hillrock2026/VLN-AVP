// ============================================================
// Agent Kernel - KernelObserver (Foundation Layer)
// ============================================================
// Owner-scoped observation and notification mechanics.
//
// P1-IS001 Kernel Foundation scope:
// - KernelObserver provides the base observer callback
//   contract; ObserverRegistry provides storage and iteration
//   for the observers attached to ONE owner-specific object.
// - Owner-specific objects compose ObserverRegistry to expose
//   technical observation of their own state.
//
// NON-responsibilities (P1-IS001):
// - KernelObserver/ObserverRegistry is a technical observation
//   mechanism, NOT Agent coordination and NOT the Runtime Event
//   Bus.
// - It does NOT publish Runtime execution events.
// - It does NOT coordinate peer subsystems.
// - It does NOT create implicit lifecycle transitions and does
//   NOT mutate another subsystem's state.
// - Observers remain scoped to the composing owner; there is no
//   global or ambient event surface.
// ============================================================

#pragma once

#include <cstdint>
#include <memory>
#include <vector>

namespace ak {

// ============================================================
// KernelObserver - abstract base for all observers
// ============================================================
class KernelObserver {
public:
    virtual ~KernelObserver() noexcept = default;

    // Called when the observed object's state changes.
    virtual void OnStateChanged(uint64_t objectId,
                                uint8_t newState) = 0;

    // Called when the observed object encounters an error.
    // message is a human-readable description, valid for the
    // duration of the call.
    virtual void OnError(uint64_t objectId,
                         uint8_t state,
                         const char* message) = 0;
};

// ============================================================
// ObserverRegistry - owner-scoped observer storage
// ============================================================
// Provides storage and iteration for the observer set of one
// owner-specific object. Concrete Kernel Objects compose this
// to support observation of their own state.
class ObserverRegistry {
public:
    ObserverRegistry() = default;
    ~ObserverRegistry() noexcept = default;

    ObserverRegistry(const ObserverRegistry&) = delete;
    ObserverRegistry& operator=(const ObserverRegistry&) = delete;
    ObserverRegistry(ObserverRegistry&&) noexcept;
    ObserverRegistry& operator=(ObserverRegistry&&) noexcept;

    void Attach(std::shared_ptr<KernelObserver> observer);
    void Detach(KernelObserver* observer);

protected:
    // Notifies all attached observers of a state change.
    void NotifyStateChange(uint64_t objectId, uint8_t newState);

    // Notifies all attached observers of an error.
    void NotifyError(uint64_t objectId, uint8_t state,
                     const char* message);

private:
    // Storage: vector of weak_ptrs to allow the observer to
    // outlive the observed object if detached late.
    std::vector<std::weak_ptr<KernelObserver>> observers_;
};

}  // namespace ak