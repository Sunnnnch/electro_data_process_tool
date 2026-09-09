"""Configure ordinary desktop storage; the explicit smoke harness isolates first."""
from __future__ import annotations

import sys
from pathlib import Path

if "--desktop-smoke" not in sys.argv[1:]:
    from electrochem_v6.desktop.data import configure_desktop_environment, resolve_desktop_data_dir
    configure_desktop_environment(resolve_desktop_data_dir(Path(sys.executable).resolve().parent))
