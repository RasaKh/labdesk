#!/usr/bin/env python3
"""WSGI entry point: `wsgi:app`.

Standard target for every Python web app on this box. gunicorn is started as:

    gunicorn ... wsgi:app

LabDesk exposes a FACTORY (`labdesk.api.create_app`), not a module-level
application, so this module is the single place that calls it once and exposes
the resulting object as `app`.

Why the parentheses matter elsewhere: a factory must be written `pkg:factory()`
when named directly on the gunicorn command line, because gunicorn otherwise
treats the factory itself as the WSGI callable and calls it as
`factory(environ, start_response)`. Naming `app` here avoids that entirely — no
parentheses, nothing to get wrong.

`run.py` remains the human-facing entry point (`python run.py --port 8080`) and
calls the same factory, so both paths share one application definition.
"""
import os
import sys

# Resolve relative to this file, not the working directory, so the app imports
# whether gunicorn starts from the project root or anywhere else.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from labdesk.api import create_app  # noqa: E402

# Call the factory exactly once, at import. gunicorn imports this module in
# each worker process, which is correct: each worker gets its own app instance,
# as it must.
app = create_app()