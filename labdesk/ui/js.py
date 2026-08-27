"""Compatibility export for extensions that imported ``JS`` directly."""
from pathlib import Path
JS = (Path(__file__).resolve().parent.parent / "static" / "app.js").read_text(encoding="utf-8")
