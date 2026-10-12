# configs/

Configuration for VLN-AVP. Phase 1 defines the directory only; no concrete
schema is frozen yet.

Planned contents (added when the corresponding module lands):

- Pipeline configuration: observation cadence, task step limits, timeouts.
- Kernel-client configuration: how the Intelligence side reaches the Kernel
  authorization boundary (integration mechanism is a Phase-2 decision).
- Model-adapter configuration: ZDTaichu5.0-9B endpoint / weights location,
  referenced by path or URL only.

Rules:

- No secrets, tokens, endpoints, or model weights are committed here. Use
  environment variables or an external secret store (see `.gitignore`).
- Configuration must not encode physical execution parameters (motor, joint,
  velocity, torque). Those belong to the Capability layer, below the Kernel.
