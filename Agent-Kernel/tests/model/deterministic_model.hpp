// ============================================================
// deterministic_model.hpp - P1-IS008 Rev1.0 test double
// ============================================================
// TEST ONLY (P1-IS008 Rev1.0 Chapters 13, 27). The deterministic
// Model required for acceptance: no network, no credentials, no
// external SDK, no GPU, no Runtime service, deterministic
// behavior. It implements the ak::model::Model contract and
// returns ModelResult; it never executes Tool and creates no
// Agent execution authority (Chapter 13).
//
// Required deterministic cases (Chapter 13):
//   successful inference   (kEcho / kFixedSuccess / kToolThenComplete)
//   invalid result         (kInvalidResult)
//   model failure          (kFailure, kInvalidInput)
//   unavailable provider   (kUnavailableOnInitialize)
//
// Never compiled into a production target (Chapter 16). Lives in
// tests/ only (OBS-03 pattern of the First Working Agent Sprint).
// ============================================================

#pragma once

#include <cstddef>
#include <string>
#include <utility>

#include <compare>
#include <agent_kernel/foundation/kernel_lifecycle.hpp>
#include <agent_kernel/model/model.hpp>

namespace ak::model {
namespace test {

// Deterministic behavior modes of the test double.
enum class DeterministicModelMode {
    kEcho,                  // Success("echo:" + input content)
    kFixedSuccess,          // Success(fixed payload)
    kInvalidResult,         // InvalidResult(fixed diagnostic)
    kFailure,               // Failure(kModelFailure, fixed diagnostic)
    kInvalidInput,          // Failure(kInvalidInput, fixed diagnostic)
    kUnavailableOnInitialize,  // Initialize() -> kUnavailable
    kToolThenComplete       // call 1: Success(payload); later: Success("complete")
};

// Deterministic Model boundary double (TEST ONLY).
class DeterministicModel final : public ak::model::Model {
public:
    DeterministicModel(ak::model::ModelId id,
                       DeterministicModelMode mode,
                       std::string payload = "deterministic-payload",
                       std::string diagnostic = "deterministic-failure")
        : id_(std::move(id)),
          mode_(mode),
          payload_(std::move(payload)),
          diagnostic_(std::move(diagnostic)) {}

    ak::model::ModelId Id() const noexcept override { return id_; }

    ak::model::ModelLifecycleState State() const noexcept override {
        return state_;
    }

    ak::TransitionResult Initialize() override {
        if (state_ != ak::model::ModelLifecycleState::kUninitialized) {
            return {ak::TransitionStatus::kRejected,
                    "deterministic model is not in the Uninitialized state"};
        }
        if (mode_ == DeterministicModelMode::kUnavailableOnInitialize) {
            state_ = ak::model::ModelLifecycleState::kUnavailable;
            return {ak::TransitionStatus::kAccepted,
                    "deterministic model is unavailable (provider unavailable)"};
        }
        state_ = ak::model::ModelLifecycleState::kReady;
        return {ak::TransitionStatus::kAccepted, ""};
    }

    ak::TransitionResult Shutdown() override {
        if (state_ != ak::model::ModelLifecycleState::kReady &&
            state_ != ak::model::ModelLifecycleState::kUnavailable) {
            return {ak::TransitionStatus::kRejected,
                    "deterministic model cannot shut down from the current state"};
        }
        state_ = ak::model::ModelLifecycleState::kShutdown;
        return {ak::TransitionStatus::kAccepted, ""};
    }

    ak::model::ModelResult Infer(const ak::model::ModelInput& input) override {
        ++inference_count_;
        last_input_content_ = input.Content();

        if (state_ != ak::model::ModelLifecycleState::kReady) {
            if (state_ == ak::model::ModelLifecycleState::kUninitialized) {
                return ak::model::ModelResult::Failure(
                    "model is not initialized",
                    ak::model::ModelErrorCategory::kModelFailure);
            }
            if (state_ == ak::model::ModelLifecycleState::kUnavailable) {
                return ak::model::ModelResult::Failure(
                    "model is unavailable",
                    ak::model::ModelErrorCategory::kModelFailure);
            }
            return ak::model::ModelResult::Failure(
                "model is shut down",
                ak::model::ModelErrorCategory::kModelFailure);
        }

        switch (mode_) {
            case DeterministicModelMode::kEcho:
                return ak::model::ModelResult::Success(
                    "echo:" + input.Content());
            case DeterministicModelMode::kFixedSuccess:
                return ak::model::ModelResult::Success(payload_);
            case DeterministicModelMode::kInvalidResult:
                return ak::model::ModelResult::InvalidResult(diagnostic_);
            case DeterministicModelMode::kFailure:
                return ak::model::ModelResult::Failure(diagnostic_);
            case DeterministicModelMode::kInvalidInput:
                return ak::model::ModelResult::Failure(
                    diagnostic_, ak::model::ModelErrorCategory::kInvalidInput);
            case DeterministicModelMode::kUnavailableOnInitialize:
                return ak::model::ModelResult::Failure(
                    "model is unavailable",
                    ak::model::ModelErrorCategory::kModelFailure);
            case DeterministicModelMode::kToolThenComplete:
                if (inference_count_ == 1) {
                    return ak::model::ModelResult::Success(payload_);
                }
                return ak::model::ModelResult::Success("complete");
        }
        return ak::model::ModelResult::Failure(
            "unknown deterministic model mode");
    }

    // -- test observables --
    [[nodiscard]] std::size_t inference_count() const noexcept {
        return inference_count_;
    }
    [[nodiscard]] const std::string& last_input_content() const noexcept {
        return last_input_content_;
    }

private:
    ak::model::ModelId id_;
    ak::model::ModelLifecycleState state_ =
        ak::model::ModelLifecycleState::kUninitialized;
    DeterministicModelMode mode_;
    std::string payload_;
    std::string diagnostic_;
    std::size_t inference_count_ = 0;
    std::string last_input_content_;
};

}  // namespace test
}  // namespace ak::model
