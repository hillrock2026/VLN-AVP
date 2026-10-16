// ============================================================
// test_doubles.hpp - P1-IS006 Rev2 Tool test doubles
// ============================================================
// Test-only Provider and Extension implementations. The real
// Tool root (Tool) is never replaced by a double in the
// production composition tests (P1-IS006 Rev2 Chapter 33.10).
// ============================================================

#pragma once

#include <agent_kernel/tool/tool.hpp>

#include <functional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace ak::tool {
namespace test {

// Builds a ToolCapability with deterministic Tool-owned fields.
inline ToolCapability MakeCapability(
    const std::string& id,
    const std::string& provider_id,
    CapabilityAvailability availability = CapabilityAvailability::kAvailable,
    bool constrained = false) {
    CapabilityInputContract input{"schema-input", "json", "input description"};
    CapabilityOutputContract output{"schema-output", "json", "output description"};
    CapabilityConstraintSet constraints;
    if (constrained) {
        constraints.constraints.push_back("tool-owned-condition");
        constraints.constrained = true;
    }
    CapabilityMetadata metadata{"cap-" + id, "author", {"tag"}, "notes"};
    return ToolCapability(CapabilityId(id), "description", "category",
                          input, output, constraints, metadata,
                          availability, ProviderId(provider_id), "1.0");
}

// Test Provider: configurable description, availability and
// preparation behavior, including failure and re-entrancy
// hooks. Never owns Tool state.
class TestToolProvider final : public IToolProvider {
public:
    explicit TestToolProvider(std::string id, bool available_value = true)
        : available(available_value), id_(std::move(id)) {}

    // -- configurable behavior --
    std::vector<ToolCapability> capabilities;
    bool available = true;
    std::string prepared_token = "prepared-token";
    bool throw_on_describe = false;
    bool throw_on_prepare = false;
    bool report_unavailable = false;
    std::function<void()> describe_hook;
    std::function<void()> prepare_hook;
    bool* destroyed = nullptr;

    // -- IToolProvider --
    ProviderId Id() const noexcept override { return id_; }

    std::vector<ToolCapability> DescribeCapabilities() const override {
        if (throw_on_describe) {
            throw std::runtime_error("test provider DescribeCapabilities raised");
        }
        if (describe_hook) {
            describe_hook();
        }
        return capabilities;
    }

    bool IsAvailable() const noexcept override { return available; }

    InvocationPreparationResult PrepareInvocation(
        const CapabilityId& capability,
        const InvocationRequest& request) const override {
        if (throw_on_prepare) {
            throw std::runtime_error("test provider PrepareInvocation raised");
        }
        if (prepare_hook) {
            prepare_hook();
        }
        if (report_unavailable) {
            return {InvocationPreparationStatus::kUnavailable, capability,
                    id_, "", "test provider reports unavailable"};
        }
        (void)request;
        return {InvocationPreparationStatus::kPrepared, capability, id_,
                prepared_token, "test provider prepared"};
    }

    ~TestToolProvider() override {
        if (destroyed) {
            *destroyed = true;
        }
    }

private:
    ProviderId id_;
};

// Test Extension: counts attach/detach and records the context
// identity. Never owns Tool state.
class TestToolExtension final : public IToolExtension {
public:
    explicit TestToolExtension(std::string name) : name_(std::move(name)) {}

    // -- configurable behavior --
    std::size_t attach_count = 0;
    std::size_t detach_count = 0;
    const ToolId* attached_tool_id = nullptr;
    bool throw_on_name = false;
    bool throw_on_attach = false;
    bool throw_on_detach = false;
    std::function<void(IToolExtensionContext&)> attach_hook;
    std::function<void(IToolExtensionContext&)> detach_hook;
    bool* destroyed = nullptr;

    // -- IToolExtension --
    std::string Name() const override {
        if (throw_on_name) {
            throw std::runtime_error("test extension Name raised");
        }
        return name_;
    }

    void Attach(IToolExtensionContext& context) override {
        ++attach_count;
        attached_tool_id = &context.Id();
        if (throw_on_attach) {
            throw std::runtime_error("test extension Attach raised");
        }
        if (attach_hook) {
            attach_hook(context);
        }
    }

    void Detach(IToolExtensionContext& context) override {
        ++detach_count;
        if (throw_on_detach) {
            throw std::runtime_error("test extension Detach raised");
        }
        if (detach_hook) {
            detach_hook(context);
        }
    }

    ~TestToolExtension() override {
        if (destroyed) {
            *destroyed = true;
        }
    }

private:
    std::string name_;
};

}  // namespace test
}  // namespace ak::tool