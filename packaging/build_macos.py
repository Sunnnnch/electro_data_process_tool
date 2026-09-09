"""Native macOS .app, ZIP and drag-to-Applications DMG; no release upload."""
from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from macos_support import artifact_prefix, check_macho, read_app_version, sha256


def run(arguments: list[str], **options) -> subprocess.CompletedProcess:
    return subprocess.run(arguments, check=True, **options)


def make_icon(source: Path, destination: Path) -> None:
    from PIL import Image
    with Image.open(source) as original:
        image = original.convert("RGBA")
        image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        canvas.paste(image, ((1024 - image.width) // 2, (1024 - image.height) // 2))
        canvas.save(destination, format="ICNS")


def build(root: Path, output: Path, arch: str) -> dict:
    if sys.platform != "darwin" or platform.machine() != arch:
        raise ValueError("Each package must be built on its matching native macOS architecture.")
    if sys.version_info[:2] != (3, 12):
        raise ValueError("Use Python 3.12 and packaging/requirements-macos.txt.")
    if int(platform.mac_ver()[0].split(".")[0]) < 13:
        raise ValueError("The build requires macOS 13 or newer.")
    version = read_app_version(root)
    prefix = artifact_prefix(version, arch)
    output.mkdir(parents=True, exist_ok=True)
    targets = [output / "ElectroChem.app", output / "ElectroChem", output / f"{prefix}.zip",
               output / f"{prefix}.dmg", output / f"{prefix}.build.json"]
    if any(path.exists() for path in targets):
        raise ValueError("Build output exists; select a fresh --output directory. Existing builds are preserved.")
    with tempfile.TemporaryDirectory(prefix="electrochem-macos-build-") as temporary:
        scratch = Path(temporary)
        icon = scratch / "app_icon.icns"
        make_icon(root / "src/electrochem_v6/desktop/assets/app_icon.png", icon)
        environment = {**os.environ, "MACOSX_DEPLOYMENT_TARGET": "13.0", "ELECTROCHEM_MACOS_ARCH": arch,
                       "ELECTROCHEM_MACOS_ICON": str(icon), "PYTHONHASHSEED": "0", "MPLBACKEND": "Agg", "PYTHONPATH": str(root / "src")}
        run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(output),
             "--workpath", str(scratch / "work"), str(root / "packaging/electrochem_macos.spec")], cwd=root, env=environment)
        app = output / "ElectroChem.app"
        info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
        if info["CFBundleExecutable"] != "ElectroChem" or info["CFBundleShortVersionString"] != version:
            raise ValueError("Generated application metadata does not match APP_VERSION.")
        macho = []
        for path in sorted(app.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            slices = check_macho(path, arch, executable=path.parent == app / "Contents/MacOS")
            if slices:
                macho.append({"path": path.relative_to(app).as_posix(), "slices": slices})
        run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--all-architectures", str(app)])
        signature = run(["/usr/bin/codesign", "--display", "--verbose=4", str(app)], capture_output=True, text=True)
        if "Signature=adhoc" not in signature.stderr or "Authority=" in signature.stderr:
            raise ValueError("This CI candidate must report its actual ad-hoc signing state.")
        zip_path, dmg_path = output / f"{prefix}.zip", output / f"{prefix}.dmg"
        run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(zip_path)])
        stage = scratch / "dmg"
        stage.mkdir()
        run(["/usr/bin/ditto", str(app), str(stage / "ElectroChem.app")])
        (stage / "Applications").symlink_to("/Applications", target_is_directory=True)
        (stage / "安装说明 - Read me.txt").write_text(
            "ElectroChem macOS candidate\n\n"
            "将 ElectroChem.app 拖入 Applications 后从应用程序打开。\n"
            "Drag ElectroChem.app to Applications, then open it from Applications.\n\n"
            f"此包架构 / Architecture: {arch}. Apple Silicon 选择 arm64；Intel 选择 x64。\n"
            "要求 / Requires: macOS 13 or later.\n"
            "此候选包仅采用 ad-hoc 签名，未经 Apple 公证；macOS 可能阻止首次打开。\n"
            "This candidate is ad-hoc signed and not Apple-notarized. macOS may block its first launch.\n"
            "请从项目正式渠道核对来源及 SHA-256；不要关闭系统安全保护。\n"
            "Verify the official project source and SHA-256; do not disable system security protections.\n"
            "https://github.com/Sunnnnch/electro_data_process_tool\n", encoding="utf-8")
        run(["/usr/bin/hdiutil", "create", "-volname", "ElectroChem", "-srcfolder", str(stage),
             "-format", "UDZO", str(dmg_path)])
        assets = []
        for artifact in (zip_path, dmg_path):
            digest = sha256(artifact)
            artifact.with_name(artifact.name + ".sha256").write_text(f"{digest}  {artifact.name}\n", encoding="ascii")
            assets.append({"name": artifact.name, "size_bytes": artifact.stat().st_size, "sha256": digest})
        packages = json.loads(run([sys.executable, "-m", "pip", "list", "--format=json"], capture_output=True, text=True).stdout)
        commit = run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
        report = {"status": "built", "version": version, "source_commit": commit, "architecture": arch,
                  "minimum_macos": "13.0", "builder_macos": platform.mac_ver()[0], "python": platform.python_version(),
                  "created_at": datetime.now(timezone.utc).isoformat(), "signature": "ad-hoc", "notarized": False,
                  "public_release_eligible": False, "icon_source_sha256": sha256(root / "src/electrochem_v6/desktop/assets/app_icon.png"),
                  "artifacts": assets, "native_binaries": macho, "dependencies": packages}
        (output / f"{prefix}.build.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", required=True, choices=["arm64", "x86_64"])
    parser.add_argument("--output", required=True, type=Path, help="Fresh output directory; previous builds are never removed")
    args = parser.parse_args()
    report = build(Path(__file__).resolve().parents[1], args.output.expanduser().resolve(), args.arch)
    print(json.dumps({"status": report["status"], "architecture": report["architecture"], "artifacts": report["artifacts"]}))


if __name__ == "__main__":
    main()
