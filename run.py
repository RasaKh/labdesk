#!/usr/bin/env python3
"""LabDesk entry point.

    python run.py                  # http://127.0.0.1:5055
    python run.py --port 8080 --host 0.0.0.0
"""

import argparse
import os
import sys

# Resolve the package relative to this file, not to the working directory,
# so `python /anywhere/run.py` and `cd anywhere && python run.py` both work.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from labdesk import APP_NAME, APP_VERSION
    from labdesk.api import create_app
    from labdesk.config import CONF_DIR, dependency_report
except ModuleNotFoundError as exc:
    if exc.name != "labdesk":
        raise
    print("Could not import the labdesk package.\n")
    print(f"  run.py is at: {_HERE}")
    print(f"  expecting:    {os.path.join(_HERE, 'labdesk', '__init__.py')}")
    print(f"  exists:       {os.path.exists(os.path.join(_HERE, 'labdesk', '__init__.py'))}\n")
    print("The layout should be:\n")
    print("  labdesk/            <- run.py lives here")
    print("    run.py")
    print("    requirements.txt")
    print("    labdesk/          <- the package")
    print("      __init__.py")
    print("      api.py  ...")
    print("      runners/")
    print("      ui/\n")
    print("If the inner folder is missing or was flattened, the package files "
          "landed in the wrong place. Move them into labdesk/labdesk/.")
    raise SystemExit(1)


def main():
    ap = argparse.ArgumentParser(description=f"{APP_NAME} {APP_VERSION}")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5055)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    missing = [d for d in dependency_report() if not d["ok"]]
    required = [d for d in missing if d["required"]]
    if required:
        print("Missing required packages:")
        for d in required:
            print(f"  {d['pip']:<16} {d['why']}\n                   {d['install']}")
        raise SystemExit(1)
    if missing:
        print(f"{len(missing)} optional packages missing; the tests that need them are "
              "greyed out in the interface. See the Settings pane for the pip lines.")

    print(f"{APP_NAME} {APP_VERSION}")
    print(f"  config   {CONF_DIR}")
    print(f"  serving  http://{args.host}:{args.port}")
    create_app().run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
