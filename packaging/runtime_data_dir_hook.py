"""Select an explicit desktop storage mode before the packaged app imports config."""

from __future__ import annotations

import sys
from pathlib import Path

from electrochem_v6.desktop.data import configure_desktop_environment, resolve_desktop_data_dir


def _configure_portable_data_dir() -> None:
    root = Path(sys.executable).resolve().parent
    configure_desktop_environment(resolve_desktop_data_dir(root))


_configure_portable_data_dir()
