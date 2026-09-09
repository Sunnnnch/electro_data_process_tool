"""Install native, macOS-13-compatible wheels into the caller's virtualenv."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ensure", action="store_true", help="Reuse a successful matching dependency installation")
    args = parser.parse_args()
    if sys.platform != "darwin" or platform.machine() not in {"arm64", "x86_64"}:
        raise SystemExit("Run this script using native macOS Python.")
    if sys.version_info[:2] != (3, 12) or sys.prefix == sys.base_prefix:
        raise SystemExit("Activate a Python 3.12 virtualenv first; system Python is never modified.")
    root = Path(__file__).resolve().parents[1]
    pip = [sys.executable, "-m", "pip"]
    files = ["requirements.txt", "requirements-frozen.txt", "packaging/requirements-pack.txt", "packaging/requirements-macos.txt"]
    fingerprint = {"requirements": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files},
                   "python": platform.python_version(), "architecture": platform.machine(), "minimum_macos": "13.0"}
    marker = Path(sys.prefix) / "electrochem-macos-dependencies.json"
    if args.ensure and marker.is_file():
        try:
            if json.loads(marker.read_text(encoding="utf-8")) == fingerprint:
                if subprocess.run([*pip, "check"], capture_output=True).returncode == 0:
                    return
        except (OSError, ValueError):
            pass
    environment = {**os.environ, "MACOSX_DEPLOYMENT_TARGET": "13.0"}
    with tempfile.TemporaryDirectory(prefix="electrochem-macos-wheels-") as temporary:
        wheels = Path(temporary)
        # pywebview's tiny pure-Python proxy_tools dependency only ships an sdist.
        # Build just that wheel, then require binary wheels for the actual solve.
        subprocess.run([*pip, "wheel", "--no-deps", "--wheel-dir", str(wheels), "proxy_tools==0.1.0"], check=True, env=environment)
        subprocess.run([*pip, "download", "--only-binary=:all:", "--platform", f"macosx_13_0_{platform.machine()}",
                        "--python-version", "3.12", "--implementation", "cp", "--abi", "cp312",
                        "--dest", str(wheels), "--find-links", str(wheels), "-r", str(root / "packaging/requirements-macos.txt")],
                       check=True, env=environment)
        subprocess.run([*pip, "install", "--force-reinstall", "--no-index", "--find-links", str(wheels), "-r",
                        str(root / "packaging/requirements-macos.txt")], check=True, env=environment)
    subprocess.run([*pip, "check"], check=True)
    marker.write_text(json.dumps(fingerprint, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
