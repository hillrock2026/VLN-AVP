"""VLN-AVP host client package.

The client spawns and talks to a host process over the versioned NDJSON
protocol defined in :mod:`vln.ipc.envelope`.
"""

from .host_client import HostClient

__all__ = ["HostClient"]
