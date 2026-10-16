"""VLN-AVP host client package.

The client spawns and talks to a host process over the versioned NDJSON
protocol defined in :mod:`vln.ipc.envelope`.

* :mod:`vln.client.host_client` - the NDJSON client bound to one host process.
* :mod:`vln.client.request_builder` - maps a validated ``AgentIntent`` onto an
  IPC :class:`~vln.ipc.envelope.Request` (no IPC, no submission).
"""

from .host_client import HostClient
from .request_builder import build_request

__all__ = ["HostClient", "build_request"]
