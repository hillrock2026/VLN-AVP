// ============================================================
// Agent Kernel - Model Result (Model boundary)
// ============================================================
// P1-IS008 Rev1.0 Chapter 8 - ModelResult.
//
// ModelResult is the result of one Model inference operation.
// It is a Model-owned result representation crossing the Model
// boundary and is interpreted by Agent. It is NOT:
//   ToolExecution, Runtime Task, Agent Completion, a Runtime
//   object, ModelAction, or Agent lifecycle state (Chapter 8).
//
// Minimum representation distinguishes:
//   Success, InvalidResult, Failure
// and carries a payload/output when appropriate and diagnostic
// information when appropriate (Chapter 8).
//
// A valid ModelResult has internally consistent status and
// required payload/diagnostic fields: a Success result carries
// a non-empty payload; InvalidResult and Failure carry a
// non-empty diagnostic (Chapter 8 validity semantics).
//
// Provider-neutral error categories (Chapter 14):
//   InvalidInput, ModelFailure, InvalidResult.
// Provider-specific errors are mapped behind the Model boundary.
//
// ModelResult uses value semantics suitable for synchronous
// Agent interpretation (Chapter 8); Rev1 does not require
// shared/background/streaming lifetimes.
//
// NON-responsibilities:
// - ModelResult is not an execution authority; it does not
//   execute Tools and does not replace ModelAction.
// ============================================================

#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <utility>

namespace ak::model {

// The canonical inference-result status (Chapter 8).
enum class ModelStatus : std::uint8_t {
    kSuccess = 0,
    kInvalidResult,
    kFailure
};

// Provider-neutral failure classification (Chapter 14).
enum class ModelErrorCategory : std::uint8_t {
    kNone = 0,
    kInvalidInput,
    kModelFailure,
    kInvalidResult
};

// The Model-owned inference result crossing the Model boundary.
class ModelResult final {
public:
    // Success requires a non-empty payload: an empty model
    // output is a deterministic invalid result, not a valid
    // success (Chapter 8 validity semantics).
    static ModelResult Success(std::string payload);

    // Invalid provider output: no payload, diagnostic required.
    static ModelResult InvalidResult(std::string diagnostic);

    // Model/provider failure: no payload, diagnostic required.
    // The optional provider-neutral category defaults to
    // kModelFailure and may classify kInvalidInput explicitly.
    static ModelResult Failure(
        std::string diagnostic,
        ModelErrorCategory category = ModelErrorCategory::kModelFailure);

    ModelResult(const ModelResult&) = default;
    ModelResult& operator=(const ModelResult&) = default;
    ModelResult(ModelResult&&) = default;
    ModelResult& operator=(ModelResult&&) = default;

    [[nodiscard]] ModelStatus Status() const noexcept { return status_; }
    [[nodiscard]] ModelErrorCategory ErrorCategory() const noexcept {
        return category_;
    }

    // A valid ModelResult is a Success carrying a payload.
    [[nodiscard]] bool Valid() const noexcept {
        return status_ == ModelStatus::kSuccess && payload_.has_value();
    }
    [[nodiscard]] bool IsSuccess() const noexcept {
        return status_ == ModelStatus::kSuccess;
    }
    [[nodiscard]] bool IsInvalidResult() const noexcept {
        return status_ == ModelStatus::kInvalidResult;
    }
    [[nodiscard]] bool IsFailure() const noexcept {
        return status_ == ModelStatus::kFailure;
    }

    // Present only when Status() == kSuccess.
    [[nodiscard]] const std::optional<std::string>& Payload() const noexcept {
        return payload_;
    }

    // Diagnostic/error information (invalid-result and failure
    // paths; empty on success).
    [[nodiscard]] const std::string& Diagnostic() const noexcept {
        return diagnostic_;
    }

private:
    ModelResult() = default;

    ModelStatus status_ = ModelStatus::kInvalidResult;
    ModelErrorCategory category_ = ModelErrorCategory::kInvalidResult;
    std::optional<std::string> payload_;
    std::string diagnostic_;
};

}  // namespace ak::model
