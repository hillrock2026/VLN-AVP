// ============================================================
// Agent Kernel - ModelResult Interpreter (Agent boundary)
// ============================================================
// TASK 3.4 - Agent-owned ModelResult -> ModelAction
// interpretation.
//
// Production promotion of the accepted interpretation semantics
// (TASK 2 Rev1.2 section 12.3 reference vocabulary):
//   "tool:<capability_id>:<arguments>" -> ModelAction::kToolInvoke
//   "complete"                         -> ModelAction::kComplete
//   all other kSuccess payloads        -> ModelAction::kInvalid
//   kInvalidResult                     -> ModelAction::kInvalid
//
// Ownership: Agent boundary (AK0046 section 18 / P1-IS008
// section 9). Interpretation is a pure, deterministic,
// Agent-owned function of ModelResult. It keeps ModelAction
// Agent-owned and keeps ModelResult Model-owned (P1-IS008
// section 8).
//
// Domain (M-001; TASK 3.4 Contract sections 6.8/6.10/9):
//   kSuccess / kInvalidResult ONLY.
//   ModelResult::kFailure is NOT an interpreter input: the
//   composition Status() gate intercepts kFailure immediately
//   after inference and terminates as kFailure WITHOUT calling
//   this function, WITHOUT producing any ModelAction, and
//   WITHOUT any Runtime invocation.
//
// NON-responsibilities:
// - This function NEVER invokes Runtime, Tool, Context, Memory,
//   or Agent lifecycle.
// - This function NEVER creates a new decision type and NEVER
//   fabricates an action from an empty/invalid result.
// ============================================================

#pragma once

#include <agent_kernel/fwa/model_action.hpp>
#include <agent_kernel/model/model_result.hpp>

namespace ak::model_to_runtime {

// Agent-owned deterministic interpretation of one ModelResult
// into the existing Agent-owned ModelAction (Contract section 6).
[[nodiscard]] ak::agent::ModelAction InterpretModelResult(
    const ak::model::ModelResult& result);

}  // namespace ak::model_to_runtime