// ============================================================
// Agent Kernel - Context (Context boundary)
// ============================================================
// Implementation of the Context root representation. Context
// owns its identity, configuration, store, services, extensions,
// and the Agent-facing coordination contract.
// ============================================================

#include <agent_kernel/context/context.hpp>

#include <utility>

namespace ak::context {

Context::Context(ContextIdentity identity)
    : identity_(identity),
      creation_(store_),
      access_(store_),
      update_(store_),
      composition_(store_),
      release_(store_),
      agent_contract_(*this) {}

}  // namespace ak::context
