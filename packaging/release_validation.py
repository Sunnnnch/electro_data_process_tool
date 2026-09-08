"""Read-only release gates: reviewed source identity and signed Windows assets."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

TAG_PATTERN = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
EXECUTABLES = ("ElectroChem.exe", "ElectroChem-MCP.exe")
REQUIRED_DEPENDENCIES = {
    "runtime-requirements.txt", "_internal/python312.dll", "_internal/vcruntime140.dll",
    "_internal/vcruntime140_1.dll", "_internal/ucrtbase.dll", "_internal/clr_loader/ffi/dlls/amd64/clrloader.dll",
    "_internal/pythonnet/runtime/python.runtime.dll", "_internal/webview/lib/microsoft.web.webview2.core.dll",
    "_internal/webview/lib/microsoft.web.webview2.winforms.dll",
    "_internal/webview/lib/runtimes/win-x64/native/webview2loader.dll",
}


def extract_release_notes(changelog: str, version: str) -> str:
    escaped = re.escape(version)
    heading = re.compile(rf"^##[ \t]+(?:\[{escaped}\]|{escaped})(?:[ \t]+[-—][ \t]+[^\r\n]+)?[ \t]*\r?$", re.MULTILINE)
    matches = list(heading.finditer(changelog))
    if len(matches) != 1:
        raise ValueError("Write exactly one changelog heading for the exact release version")
    remaining = changelog[matches[0].end():]
    following = re.search(r"^##[ \t]+", remaining, re.MULTILINE)
    notes = remaining[:following.start()].strip() if following else remaining.strip()
    if not notes:
        raise ValueError("Release notes must not be empty")
    return notes


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError(f"Git verification failed: {' '.join(arguments[:2])}")
    return result.stdout.strip()


def validate_source(root: Path, tag: str, expected_commit: str, *, verify_remote_tag: bool = False,
                    remote: str = "origin") -> dict[str, str]:
    if not TAG_PATTERN.fullmatch(tag):
        raise ValueError("An exact stable version tag such as v7.0.1 is required")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", expected_commit):
        raise ValueError("A full 40-character reviewed commit SHA is required")
    expected_commit = expected_commit.lower()
    head = _git(root, "rev-parse", "--verify", "HEAD")
    tagged = _git(root, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
    if head != expected_commit or tagged != expected_commit:
        raise ValueError("Release tag and checked-out HEAD must identify the reviewed commit")
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Tracked source changes exist after the reviewed commit")
    constants = {}
    config = root / "src/electrochem_v6/config.py"
    for statement in ast.parse(config.read_text(encoding="utf-8-sig")).body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and target.id in {"APP_NAME", "APP_VERSION"}:
                    constants[target.id] = ast.literal_eval(statement.value)
    version = tag[1:]
    if constants.get("APP_VERSION") != version:
        raise ValueError("Tag version does not match APP_VERSION in the reviewed source")
    name = constants.get("APP_NAME")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("APP_NAME must be a nonempty string constant")
    if verify_remote_tag:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", remote):
            raise ValueError("Use a configured Git remote name")
        rows = _git(root, "ls-remote", "--tags", remote, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}")
        refs = {line.split()[1]: line.split()[0] for line in rows.splitlines() if len(line.split()) == 2}
        remote_commit = refs.get(f"refs/tags/{tag}^{{}}", refs.get(f"refs/tags/{tag}"))
        if remote_commit != expected_commit:
            raise ValueError("Remote release tag is missing or no longer identifies the reviewed commit")
    return {"tag": tag, "version": version, "commit": head, "product_name": name}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_checksum(path: Path) -> str:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Release artifact is missing or empty: {path.name}")
    digest = _sha256(path)
    checksum = Path(str(path) + ".sha256")
    if not checksum.is_file() or checksum.read_text(encoding="ascii").strip() != f"{digest} *{path.name}":
        raise ValueError(f"Release checksum mismatch or missing: {path.name}")
    return digest


def _read_windows_info(paths: list[Path]) -> list[dict[str, Any]]:
    if os.name != "nt":
        raise ValueError("Windows Authenticode verification is required for official binary releases")
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        raise ValueError("PowerShell is required for Windows signature verification")
    command = (
        "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        "@(ConvertFrom-Json $env:ELECTROCHEM_RELEASE_FILES | ForEach-Object { "
        "$f=Get-Item -LiteralPath $_; $s=Get-AuthenticodeSignature -LiteralPath $_; "
        "[PSCustomObject]@{filename=$f.Name;product_name=$f.VersionInfo.ProductName;"
        "version=$f.VersionInfo.ProductVersion;original_filename=$f.VersionInfo.OriginalFilename;"
        "signature=$s.Status.ToString();signer=$s.SignerCertificate.Thumbprint}}) | ConvertTo-Json -Compress"
    )
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", command],
                            env={**os.environ, "ELECTROCHEM_RELEASE_FILES": json.dumps([str(path) for path in paths])},
                            capture_output=True, text=True, encoding="utf-8-sig", timeout=90)
    if result.returncode:
        raise ValueError("Unable to read Windows executable versions and signatures")
    info = json.loads(result.stdout)
    if not isinstance(info, list) or len(info) != len(paths):
        raise ValueError("Incomplete Windows executable verification")
    return info


def _read_webview2_info(path: Path) -> dict[str, Any]:
    """Reuse the build gate to verify Microsoft's signature and signed x64 payload."""
    if os.name != "nt":
        raise ValueError("Windows verification is required for an offline runtime")
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        raise ValueError("PowerShell is required for offline runtime verification")
    helper = Path(__file__).resolve().with_name("installer_prerequisites.ps1")
    command = (
        "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        ". $env:ELECTROCHEM_RELEASE_PREREQUISITES; "
        "Get-ValidatedWebView2Installer $env:ELECTROCHEM_RELEASE_WEBVIEW2 | ConvertTo-Json -Depth 8 -Compress"
    )
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", command],
                            env={**os.environ, "ELECTROCHEM_RELEASE_PREREQUISITES": str(helper),
                                 "ELECTROCHEM_RELEASE_WEBVIEW2": str(path.resolve())},
                            capture_output=True, text=True, encoding="utf-8-sig", timeout=180)
    if result.returncode:
        raise ValueError("Offline WebView2 signature or signed runtime payload verification failed")
    info = json.loads(result.stdout)
    if not isinstance(info, dict):
        raise ValueError("Incomplete offline runtime verification")
    info.pop("path", None)
    return info


def _validate_dependency_manifest(path: Path, source: dict[str, str], installer: Path, digest: str,
                                  archive: zipfile.ZipFile, entries: dict[str, zipfile.ZipInfo], *,
                                  runtime: dict[str, Any] | None = None) -> str:
    manifest_digest = _verify_checksum(path)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Dependency manifest is too large")
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    variant = "offline" if runtime is not None else "standard"
    if (not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1
            or manifest.get("applicationVersion") != source["version"] or manifest.get("variant") != variant
            or manifest.get("installer") != {"filename": installer.name, "sha256": digest}):
        raise ValueError("Dependency manifest does not identify the exact release installer")
    platform = manifest.get("platform", {})
    if platform != {"os": "Windows", "minimumBuild": 19045, "architecture": "x64", "arm64": "not-supported-by-installer"}:
        raise ValueError("Dependency manifest has an unsupported platform policy")
    prerequisites = manifest.get("prerequisites")
    expected = {
        "webview2": {"minimumMajor": 120, "bundled": runtime is not None, "installer": runtime},
        "dotnetFramework": {"minimumVersion": "4.6.2", "suppliedByTargetWindows": True, "bundledInstaller": False},
        "visualCpp": {"distribution": "application-local", "bundledInstaller": False},
        "python": {"version": "3.12", "distribution": "application-local"},
    }
    if prerequisites != expected:
        raise ValueError("Dependency manifest does not match the verified runtime and prerequisite policy")
    dependencies = manifest.get("dependencyFiles")
    if not isinstance(dependencies, list) or not dependencies:
        raise ValueError("Dependency manifest has no bundled runtime inventory")
    seen = set()
    for item in dependencies:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("Invalid dependency inventory entry")
        name = item["path"].casefold()
        entry = entries.get(name)
        if name in seen or entry is None or entry.is_dir() or not 0 < entry.file_size <= 256 * 1024 * 1024:
            raise ValueError("Dependency inventory contains a duplicate or missing portable runtime file")
        seen.add(name)
        with archive.open(entry) as stream:
            checksum = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(chunk)
            actual = checksum.hexdigest()
        if item.get("sha256") != actual or item.get("bytes") != entry.file_size:
            raise ValueError(f"Bundled runtime hash or size does not match the portable archive: {item['path']}")
    if not REQUIRED_DEPENDENCIES <= seen or not any(re.fullmatch(r"_internal/numpy\.libs/msvcp140[^/]*\.dll", name) for name in seen):
        raise ValueError("Dependency inventory is missing required application-local runtimes")
    with archive.open(entries["runtime-requirements.txt"]) as stream:
        requirements = [line for line in stream.read().decode("utf-8-sig").splitlines() if line.strip()]
    if manifest.get("runtimeRequirements") != requirements:
        raise ValueError("Dependency manifest runtime requirements differ from the portable archive")
    return manifest_digest


def validate_artifacts(source: dict[str, str], portable_zip: Path, installer: Path, *,
                       offline_installer: Path | None = None, webview2_installer: Path | None = None) -> dict[str, Any]:
    version = source["version"]
    if portable_zip.name != f"ElectroChem-{version}-win64.zip" or installer.name != f"ElectroChem-Setup-{version}.exe":
        raise ValueError("Release artifact filenames must match the exact source version")
    if (offline_installer is None) != (webview2_installer is None):
        raise ValueError("Offline installer and its verified WebView2 source must be supplied together")
    if offline_installer is not None and offline_installer.name != f"ElectroChem-Setup-{version}-offline.exe":
        raise ValueError("Offline installer filename must match the exact source version")
    installers = [installer] if offline_installer is None else [installer, offline_installer]
    digests = {path.name: _verify_checksum(path) for path in (portable_zip, *installers)}
    runtime = _read_webview2_info(webview2_installer) if webview2_installer is not None else None
    manifests = []
    with zipfile.ZipFile(portable_zip) as archive, tempfile.TemporaryDirectory(prefix="electrochem-release-") as temp:
        entries = {}
        for entry in archive.infolist():
            name = entry.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            if not parts or name.startswith("/") or ":" in name or ".." in parts:
                raise ValueError("Portable archive contains an unsafe member path")
            if name.casefold() in entries:
                raise ValueError("Portable archive contains duplicate member names")
            if parts[0].casefold() in {"user_data", "installed.marker"}:
                raise ValueError("Portable archive includes user data or an installed-mode marker")
            entries[name.casefold()] = entry
        if "portable.marker" not in entries or not any(name.startswith("_internal/") for name in entries):
            raise ValueError("Portable archive is missing its marker or shared runtime")
        binaries = []
        for name in EXECUTABLES:
            entry = entries.get(name.casefold())
            if entry is None or entry.is_dir() or not 0 < entry.file_size <= 256 * 1024 * 1024:
                raise ValueError(f"Portable archive is missing a valid {name}")
            # Extract only these fixed names; archive paths never select a target.
            target = Path(temp) / name
            with archive.open(entry) as incoming, target.open("wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            binaries.append(target)
        for current in installers:
            manifest = Path(str(current) + ".dependencies.json")
            # Previous standard-only releases remain valid; new manifests and every
            # offline release must be checked against the real packaged runtime.
            if manifest.exists() or offline_installer is not None:
                digests[manifest.name] = _validate_dependency_manifest(
                    manifest, source, current, digests[current.name], archive, entries,
                    runtime=runtime if current == offline_installer else None,
                )
                manifests.append(manifest.name)
        information = _read_windows_info([*binaries, *(path.resolve() for path in installers)])
        signers = set()
        for info, name in zip(information, [*EXECUTABLES, *(path.name for path in installers)], strict=True):
            if info.get("filename") != name or str(info.get("version", "")).strip() != version:
                raise ValueError(f"Executable version does not match the release tag: {name}")
            if str(info.get("product_name", "")).strip() != source["product_name"]:
                raise ValueError(f"Executable product identity is incorrect: {name}")
            if name in EXECUTABLES and info.get("original_filename") != name:
                raise ValueError(f"Portable executable identity is incorrect: {name}")
            if info.get("signature") != "Valid" or not info.get("signer"):
                raise ValueError(f"Official release requires a verified Authenticode signature: {name}")
            signers.add(info["signer"])
        if len(signers) != 1:
            raise ValueError("GUI, MCP companion, and installers must use the same publisher certificate")
    return {**source, "sha256": digests, "signed_executables": information, "dependency_manifests": manifests,
            "offline_runtime": runtime}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--tag", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--source-only", action="store_true")
    parser.add_argument("--print-notes", action="store_true", help="Print this exact version's changelog section after source checks")
    parser.add_argument("--verify-remote-tag", action="store_true")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--portable-zip", type=Path)
    parser.add_argument("--installer", type=Path)
    parser.add_argument("--offline-installer", type=Path, help="Optional signed offline installer; requires its original WebView2 source")
    parser.add_argument("--webview2-installer", type=Path, help="Original Microsoft x64 runtime used to build the offline installer")
    args = parser.parse_args()
    try:
        report = validate_source(args.root, args.tag, args.expected_commit,
                                 verify_remote_tag=args.verify_remote_tag, remote=args.remote)
        if args.print_notes:
            print(extract_release_notes((args.root / "CHANGELOG.md").read_text(encoding="utf-8-sig"), report["version"]))
            return 0
        if not args.source_only:
            if args.portable_zip is None or args.installer is None:
                raise ValueError("Both portable ZIP and installer are required")
            report = validate_artifacts(report, args.portable_zip, args.installer,
                                        offline_installer=args.offline_installer, webview2_installer=args.webview2_installer)
        print(json.dumps(report, ensure_ascii=True))
        return 0
    except (ValueError, OSError, subprocess.TimeoutExpired, zipfile.BadZipFile) as exc:
        print(f"Release validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
