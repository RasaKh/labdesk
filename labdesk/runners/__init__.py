"""
Runner registry.

Every entry maps a test id from stats_registry to a callable with the
signature (df, roles, params, ctl) -> dict. Anything absent is a declared
stub: the UI shows it, the spec validates, and running it returns the exact
function signature to write. That is deliberate. A registry entry with no
runner is a to-do with a schema attached, not a lie.
"""

from . import basic, models, meta, bench, power

RUNNERS = {}
for _mod in (basic, models, meta, bench, power):
    RUNNERS.update(getattr(_mod, "RUNNERS", {}))
