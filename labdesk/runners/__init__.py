"""
Runner registry. Maps a test id to a callable (df, roles, params, ctl) -> dict.
"""

from . import basic

RUNNERS = {}
for _mod in (basic,):
    RUNNERS.update(getattr(_mod, "RUNNERS", {}))
