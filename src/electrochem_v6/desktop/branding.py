"""Stable desktop identity and bundled ElectroChem artwork."""

from pathlib import Path

APP_USER_MODEL_ID = "ElectroChem.Desktop"
APP_BUNDLE_ID = "org.electrochem.desktop"


def icon_path(suffix: str = "ico") -> Path:
    """Locate package data in both a source checkout and a frozen application."""
    extension = str(suffix).lower().removeprefix(".")
    if extension not in {"ico", "png", "icns"}:
        raise ValueError("Application icon format must be ico or png or icns")
    return Path(__file__).resolve().parent / "assets" / f"app_icon.{extension}"


__all__ = ["APP_USER_MODEL_ID", "APP_BUNDLE_ID", "icon_path"]
