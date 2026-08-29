"""Browser-facing assets.

Deliberately empty of logic. The stylesheet, HTML shell and client are held
as Python strings in css.py, html.py and js.py so the whole application stays
importable and deployable as a single package with no static file server, no
build step and no asset paths to get wrong.

Import from the modules directly:

    from labdesk.ui.html import page
"""
