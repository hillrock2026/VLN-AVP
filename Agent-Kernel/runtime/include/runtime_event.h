// ============================================================
// P0R0005 — RuntimeEvent (canonical Runtime event model)
// ============================================================
// Canonical Runtime event value object per AK0034 §10.
//
// RuntimeEvent is the only data structure accepted by the
// Event Bus. It represents immutable Runtime facts about
// Task / Workflow / Session lifecycle transitions.
//
// Logical structure (AK0034 §10.2):
//   EventID eventID;
//   Timestamp timestamp;
//   RuntimeEventType type;
//   ak::TaskID taskID;
//   ak::WorkflowID workflowID;
//   ak::SessionID sessionID;
//   std::string message;
//
// Immutability (AK0034 §10.5):
//   Immediately after Publish(), the RuntimeEvent becomes
//   immutable. Neither the EventBus nor subscribers may
//   modify it.
//
// Ownership (AK0034 §10.6):
//   Before publication: the publisher owns the RuntimeEvent.
//   After publication: the EventBus owns delivery.
//   Subscribers receive immutable observations only.
//
// RuntimeEventType (AK0034 §10.3):
//   Enumeration of all recognized Runtime event types.
// ============================================================

#pragma once

#include <cstdint>
#include <string>

#include <agent_kernel/object_id.hpp>

namespace ak {

// ============================================================
// RuntimeEventType — Runtime event classification
// ============================================================
enum class RuntimeEventType : std::uint8_t {
    kTaskStarted = 0,
    kTaskCompleted,
    kTaskFailed,
    kWorkflowStarted,
    kWorkflowCompleted,
    kWorkflowFailed,
    kSessionStarted,
    kSessionCompleted,
    kSessionFailed,
};

// ============================================================
// EventID — unique publication identifier (AK0034 §2.4)
// ============================================================
// Every Runtime event possesses a unique EventID.
// The EventID uniquely identifies one publication instance.
// Multiple publications of identical payloads produce distinct
// EventIDs. Physical representation is implementation-defined
// per AK0034 §10.2.
using EventID = std::uint64_t;

// ============================================================
// Timestamp — publication timestamp (AK0034 §2.5)
// ============================================================
// Each Runtime event records the publication timestamp.
// The timestamp indicates when the event entered the Runtime
// Event Bus and never changes after publication. Physical
// representation is implementation-defined per AK0034 §10.2.
using Timestamp = std::uint64_t;

// ============================================================
// RuntimeEvent — immutable Runtime event value object
// ============================================================
struct RuntimeEvent {
    // Publication metadata (AK0034 §10.2): initialized during
    // RuntimeEvent construction and stamped by the Event Bus at
    // publication entry (AK0034 §2.4 / §2.5).
    EventID eventID = 0;          // Unique publication identifier.
    Timestamp timestamp = 0;      // Publication timestamp.
    RuntimeEventType type = RuntimeEventType::kTaskStarted;
    ak::TaskID taskID;
    ak::WorkflowID workflowID;
    ak::SessionID sessionID;
    std::string message;
};

// ============================================================
// Helpers
// ============================================================

// Returns true when the event type is one of the recognized
// RuntimeEventType values defined by AK0034 §10.3.
[[nodiscard]] bool IsValidRuntimeEventType(RuntimeEventType type) noexcept;

// Returns true when the RuntimeEvent is valid (AK0034 §14.3):
// publication metadata (EventID and Timestamp) must be present,
// the type must be recognized, and the message must be non-empty.
[[nodiscard]] bool IsValidRuntimeEvent(const RuntimeEvent& event) noexcept;

}  // namespace ak
