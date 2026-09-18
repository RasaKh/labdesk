#!/usr/bin/env python3
"""Restore a LabDesk backup into a new workspace directory."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from labdesk import backup

parser = argparse.ArgumentParser()
parser.add_argument("backup")
parser.add_argument("destination")
args = parser.parse_args()
print(backup.restore(args.backup, args.destination))
