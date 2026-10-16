// ============================================================
// P0R0005 — RuntimeEvent implementation
// ============================================================
// Provides canonical Runtime event validation helpers used by
// the EventBus publication pipeline (AK0034 §14).

#include <runtime_event.h>

namespace ak {

bool IsValidRuntimeEventType(RuntimeEventType type) noexcept {
    switch (type) {
        case RuntimeEventType::kTaskStarted:
        case RuntimeEventType::kTaskCompleted:
        case RuntimeEventType::kTaskFailed:
        case RuntimeEventType::kWorkflowStarted:
        case RuntimeEventType::kWorkflowCompleted:
        case RuntimeEventType::kWorkflowFailed:
        case RuntimeEventType::kSessionStarted:
        case RuntimeEventType::kSessionCompleted:
        case RuntimeEventType::kSessionFailed:
            return true;
        default:
            return false;
    }
}

bool IsValidRuntimeEvent(const RuntimeEvent& event) noexcept {
    // AK0034 §14.3 (Stage 1 — Event Validation): validation
    // verifies EventID validity, EventType recognition, payload
    // integrity, and metadata consistency.
    //
    // A valid event must carry publication metadata (EventID and
    // Timestamp), a recognized type, and a non-empty message
    // describing the Runtime fact.
    return event.eventID != EventID{0} &&
           event.timestamp != Timestamp{0} &&
           IsValidRuntimeEventType(event.type) &&
           !event.message.empty();
}

}  // namespace ak
