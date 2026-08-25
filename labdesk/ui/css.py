"""Compatibility export for extensions that imported ``CSS`` directly."""
from pathlib import Path
CSS = (Path(__file__).resolve().parent.parent / "static" / "app.css").read_text(encoding="utf-8")
