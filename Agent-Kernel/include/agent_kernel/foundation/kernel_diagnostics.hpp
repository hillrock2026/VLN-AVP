// ============================================================
// Agent Kernel - KernelDiagnostics (Foundation Layer)
// ============================================================
// Neutral diagnostic and validation support.
//
// P1-IS001 Kernel Foundation scope:
// - KernelDiagnostic is a neutral, transport- and
//   framework-independent diagnostic value.
// - DiagnosticSink is an owner-scoped collector: an owner may
//   compose one inside its own boundary to accumulate
//   diagnostics during validation.
//
// NON-responsibilities (P1-IS001):
// - Diagnostics carry no architectural semantics and do NOT
//   own or mutate any subsystem state.
// - DiagnosticSink is NOT a cross-subsystem service and does
//   NOT coordinate subsystems.
// - There is no global or ambient diagnostic channel here.
// ============================================================

#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace ak {

// ============================================================
// DiagnosticSeverity
// ============================================================
enum class DiagnosticSeverity : std::uint8_t {
    kInfo,
    kWarning,
    kError
};

// ============================================================
// KernelDiagnostic
// ============================================================
struct KernelDiagnostic {
    DiagnosticSeverity severity = DiagnosticSeverity::kInfo;
    std::uint32_t code = 0;
    std::string message;

    [[nodiscard]] bool IsError() const noexcept {
        return severity == DiagnosticSeverity::kError;
    }
};

// ============================================================
// DiagnosticSink - owner-scoped diagnostic collector
// ============================================================
class DiagnosticSink {
public:
    DiagnosticSink() = default;
    ~DiagnosticSink() noexcept = default;

    DiagnosticSink(const DiagnosticSink&) = delete;
    DiagnosticSink& operator=(const DiagnosticSink&) = delete;
    DiagnosticSink(DiagnosticSink&&) noexcept = default;
    DiagnosticSink& operator=(DiagnosticSink&&) noexcept = default;

    void Add(KernelDiagnostic diagnostic) {
        diagnostics_.push_back(std::move(diagnostic));
    }

    void Add(DiagnosticSeverity severity, std::uint32_t code,
             std::string message) {
        diagnostics_.push_back({severity, code, std::move(message)});
    }

    void Clear() noexcept { diagnostics_.clear(); }

    [[nodiscard]] std::size_t Count() const noexcept { return diagnostics_.size(); }

    [[nodiscard]] std::size_t ErrorCount() const noexcept {
        std::size_t count = 0;
        for (const auto& diagnostic : diagnostics_) {
            if (diagnostic.IsError()) {
                ++count;
            }
        }
        return count;
    }

    [[nodiscard]] bool HasErrors() const noexcept { return ErrorCount() != 0; }

    [[nodiscard]] const std::vector<KernelDiagnostic>& All() const noexcept {
        return diagnostics_;
    }

private:
    std::vector<KernelDiagnostic> diagnostics_;
};

}  // namespace ak