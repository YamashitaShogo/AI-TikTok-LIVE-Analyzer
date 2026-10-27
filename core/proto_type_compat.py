"""Resolve deferred proto annotations before parsing payloads on worker threads."""

import sys

from pydantic.dataclasses import is_pydantic_dataclass, rebuild_dataclass


def prepare_proto_types():
    """Use defining-module namespaces, never a parser's local ``data`` bytes.

    Call after TikTokLive event imports, before starting receiver threads.
    Only incomplete TikTokLiveProto dataclasses are rebuilt. No payload or
    site-packages files are modified. Repeated calls are harmless.
    """
    seen = set()
    rebuilt = 0
    for module in list(sys.modules.values()):
        if not getattr(module, "__name__", "").startswith("TikTokLiveProto."):
            continue
        for cls in list(vars(module).values()):
            if not isinstance(cls, type) or cls in seen:
                continue
            seen.add(cls)
            if not is_pydantic_dataclass(cls):
                continue
            if getattr(cls, "__pydantic_complete__", True):
                continue
            rebuild_dataclass(cls, _parent_namespace_depth=0)
            rebuilt += 1
    return rebuilt
