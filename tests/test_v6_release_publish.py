"""Exercise exact source/asset gates and atomic pushes against disposable local Git only."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUBLISH = ROOT / "packaging/publish_release_refs.ps1"
VALIDATOR = ROOT / "packaging/release_validation.py"
_spec = importlib.util.spec_from_file_location("electrochem_release_validation", VALIDATOR)
assert _spec is not None and _spec.loader is not None
validation = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validation)
VERSION = "7.0.1"
TAG = "v7.0.1"
PRODUCT = "Release Test Product"


def _git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _checksum(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    Path(str(path) + ".sha256").write_text(f"{digest} *{path.name}\n", encoding="ascii")


def _archive(path, *, omit=(), extra=()):
    with zipfile.ZipFile(path, "w") as archive:
        for name in (*validation.EXECUTABLES, "portable.marker", "_internal/runtime.txt", *extra):
            if name not in omit:
                archive.writestr(name, b"isolated release fixture")
    _checksum(path)


def _verified_windows_info(paths):
    # Only the Windows trust-provider boundary is mocked. Real ZIP extraction,
    # hashes, source commits, tags, versions, and atomic Git pushes still run.
    return [{"filename": path.name, "product_name": PRODUCT, "version": VERSION,
             "original_filename": path.name, "signature": "Valid", "signer": "TEST-CERT"} for path in paths]


def _runtime_metadata(path):
    return {"filename": path.name, "version": "140.0.1.2", "wrapperVersion": "1.3.4.5",
            "versionSource": "signed-wrapper:B/102:Omaha-WebView2-manifest",
            "runtimeAppId": "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
            "runtimePackage": "MicrosoftEdgeWebview_X64_140.0.1.2.exe",
            "runtimePackageSha256": "a" * 64,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size,
            "signature": {"status": "Valid", "subject": "CN=Microsoft Corporation, O=Microsoft Corporation, C=US", "thumbprint": "MICROSOFT-TEST-CERT"}}


def _dependency_manifest(installer, portable, *, runtime=None):
    with zipfile.ZipFile(portable) as archive:
        files = [{"path": name, "sha256": hashlib.sha256(archive.read(name)).hexdigest(),
                  "bytes": archive.getinfo(name).file_size, "fileVersion": None}
                 for name in sorted(validation.REQUIRED_DEPENDENCIES | {"_internal/numpy.libs/msvcp140-test.dll"})]
    value = {
        "schemaVersion": 1, "applicationVersion": VERSION, "variant": "offline" if runtime else "standard",
        "installer": {"filename": installer.name, "sha256": hashlib.sha256(installer.read_bytes()).hexdigest()},
        "platform": {"os": "Windows", "minimumBuild": 19045, "architecture": "x64", "arm64": "not-supported-by-installer"},
        "prerequisites": {
            "webview2": {"minimumMajor": 120, "bundled": runtime is not None, "installer": _runtime_metadata(runtime) if runtime else None},
            "dotnetFramework": {"minimumVersion": "4.6.2", "suppliedByTargetWindows": True, "bundledInstaller": False},
            "visualCpp": {"distribution": "application-local", "bundledInstaller": False},
            "python": {"version": "3.12", "distribution": "application-local"},
        },
        "dependencyFiles": files, "runtimeRequirements": ["isolated release fixture"],
    }
    path = Path(str(installer) + ".dependencies.json")
    path.write_text(json.dumps(value), encoding="utf-8")
    _checksum(path)
    return path


def _offline_artifacts(portable, installer):
    _archive(portable, extra=tuple(validation.REQUIRED_DEPENDENCIES | {"_internal/numpy.libs/msvcp140-test.dll"}))
    offline = installer.with_name(f"ElectroChem-Setup-{VERSION}-offline.exe")
    offline.write_bytes(b"offline installer fixture")
    _checksum(offline)
    runtime = installer.with_name("MicrosoftEdgeWebView2RuntimeInstallerX64.exe")
    runtime.write_bytes(b"Microsoft runtime fixture")
    _dependency_manifest(installer, portable)
    _dependency_manifest(offline, portable, runtime=runtime)
    return offline, runtime


@pytest.fixture
def release_repo(tmp_path):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell is required for Windows release scripts")
    remote = tmp_path / "remote.git"
    checkout = tmp_path / "checkout"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "init", "-b", "main", str(checkout))
    _git(checkout, "config", "user.name", "Release Test")
    _git(checkout, "config", "user.email", "release-test@example.invalid")
    _git(checkout, "config", "commit.gpgSign", "false")
    _git(checkout, "config", "tag.gpgSign", "false")
    _git(checkout, "remote", "add", "origin", str(remote))
    config = checkout / "src/electrochem_v6/config.py"
    config.parent.mkdir(parents=True)
    config.write_text(f"APP_VERSION = '{VERSION}'\nAPP_NAME = '{PRODUCT}'\n", encoding="utf-8")
    packaging = checkout / "packaging"
    packaging.mkdir()
    shutil.copyfile(PUBLISH, packaging / PUBLISH.name)
    # Test copy only; production has no signature-bypass switch or environment.
    fake_provider = '''
def _read_windows_info(paths):
    return [{"filename": p.name, "product_name": "Release Test Product", "version": "7.0.1",
             "original_filename": p.name, "signature": "Valid", "signer": "TEST-CERT"} for p in paths]

'''
    fake_provider += inspect.getsource(_runtime_metadata).replace("def _runtime_metadata(", "def _read_webview2_info(") + "\n\n"
    (packaging / VALIDATOR.name).write_text(
        VALIDATOR.read_text(encoding="utf-8").replace('if __name__ == "__main__":', fake_provider + 'if __name__ == "__main__":'),
        encoding="utf-8",
    )
    source = checkout / "source.txt"
    source.write_text("before", encoding="utf-8")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-m", "initial")
    before = _git(checkout, "rev-parse", "HEAD")
    _git(checkout, "push", "origin", "main")
    source.write_text("release", encoding="utf-8")
    _git(checkout, "commit", "-am", "release")
    expected = _git(checkout, "rev-parse", "HEAD")
    _git(checkout, "tag", TAG)
    portable = checkout / f"ElectroChem-{VERSION}-win64.zip"
    installer = checkout / f"ElectroChem-Setup-{VERSION}.exe"
    _archive(portable)
    installer.write_bytes(b"installer fixture")
    _checksum(installer)

    def publish(*, target_branch="main", verify_only=False, expected_commit=expected, offline=None, runtime=None):
        arguments = [shell, "-NoProfile", "-NonInteractive", "-File", str(packaging / PUBLISH.name),
                     "-Tag", TAG, "-ExpectedCommit", expected_commit, "-PortableZip", str(portable),
                     "-Installer", str(installer), "-PythonPath", sys.executable]
        if target_branch:
            arguments.extend(["-TargetBranch", target_branch])
        if verify_only:
            arguments.append("-VerifyOnly")
        if offline:
            arguments.extend(["-OfflineInstaller", str(offline)])
        if runtime:
            arguments.extend(["-WebView2Installer", str(runtime)])
        return subprocess.run(arguments, cwd=checkout,
                              env={**os.environ, "PYTHONUTF8": "1"}, capture_output=True,
                              text=True, encoding="utf-8-sig", timeout=40)

    return checkout, remote, before, expected, (portable, installer), publish


@pytest.mark.parametrize("invalid", ["missing", "checksum", "empty", "missing-mcp"])
def test_missing_or_invalid_artifact_does_not_publish_refs(release_repo, invalid):
    _checkout, remote, before, _expected, artifacts, publish = release_repo
    if invalid == "missing":
        artifacts[1].unlink()
    elif invalid == "checksum":
        artifacts[1].write_bytes(b"changed after checksum")
    elif invalid == "empty":
        artifacts[1].write_bytes(b"")
    else:
        _archive(artifacts[0], omit=("ElectroChem-MCP.exe",))
    assert publish().returncode != 0
    assert _git(remote, "rev-parse", "refs/heads/main") == before
    assert _git(remote, "tag", "--list") == ""


def test_verified_artifacts_publish_only_the_explicit_branch_and_tag(release_repo):
    _checkout, remote, before, expected, _artifacts, publish = release_repo
    result = publish(target_branch="codex/release-7.0.1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(remote, "rev-parse", "refs/heads/main") == before
    assert _git(remote, "rev-parse", "refs/heads/codex/release-7.0.1") == expected
    assert _git(remote, "rev-parse", f"refs/tags/{TAG}") == expected


def test_conflicting_tag_does_not_partially_advance_branch(release_repo):
    _checkout, remote, before, _expected, _artifacts, publish = release_repo
    _git(remote, "tag", TAG, before)
    assert publish().returncode != 0
    assert _git(remote, "rev-parse", "refs/heads/main") == before
    assert _git(remote, "rev-parse", f"refs/tags/{TAG}") == before


def test_verify_only_does_not_publish_and_write_requires_explicit_branch(release_repo):
    _checkout, remote, before, _expected, _artifacts, publish = release_repo
    assert publish(target_branch=None, verify_only=True).returncode == 0
    assert publish(target_branch=None).returncode != 0
    assert _git(remote, "rev-parse", "refs/heads/main") == before
    assert _git(remote, "tag", "--list") == ""


@pytest.mark.parametrize("mismatch", ["reviewed-commit", "tag", "dirty-source", "app-version"])
def test_source_mismatch_never_publishes(release_repo, mismatch):
    checkout, remote, before, expected, _artifacts, publish = release_repo
    if mismatch == "reviewed-commit":
        expected = before
    elif mismatch == "tag":
        _git(checkout, "tag", "-f", TAG, before)
    elif mismatch == "dirty-source":
        (checkout / "source.txt").write_text("unreviewed")
    else:
        (checkout / "src/electrochem_v6/config.py").write_text(f"APP_VERSION='7.0.2'\nAPP_NAME='{PRODUCT}'\n")
        _git(checkout, "commit", "-am", "wrong version")
        _git(checkout, "tag", "-f", TAG)
        expected = _git(checkout, "rev-parse", "HEAD")
    assert publish(expected_commit=expected).returncode != 0
    assert _git(remote, "rev-parse", "refs/heads/main") == before
    assert _git(remote, "tag", "--list") == ""


def test_remote_tag_is_verified_without_changing_refs(release_repo):
    checkout, remote, _before, expected, _artifacts, _publish = release_repo
    with pytest.raises(ValueError, match="Remote release tag"):
        validation.validate_source(checkout, TAG, expected, verify_remote_tag=True)
    _git(checkout, "push", "origin", f"refs/tags/{TAG}")
    info = validation.validate_source(checkout, TAG, expected, verify_remote_tag=True)
    assert info["version"] == VERSION and info["commit"] == expected
    _git(remote, "tag", "-f", TAG, "refs/heads/main")
    with pytest.raises(ValueError, match="Remote release tag"):
        validation.validate_source(checkout, TAG, expected, verify_remote_tag=True)


@pytest.mark.parametrize("binary", [0, 1, 2])
@pytest.mark.parametrize("mismatch", ["signature", "version", "product", "signer"])
def test_each_binary_requires_matching_version_product_and_publisher(tmp_path, monkeypatch, binary, mismatch):
    portable = tmp_path / f"ElectroChem-{VERSION}-win64.zip"
    installer = tmp_path / f"ElectroChem-Setup-{VERSION}.exe"
    _archive(portable)
    installer.write_bytes(b"installer")
    _checksum(installer)

    def provider(paths):
        rows = _verified_windows_info(paths)
        field, value = {"signature": ("signature", "NotSigned"), "version": ("version", "7.0.2"),
                        "product": ("product_name", "Other"), "signer": ("signer", "OTHER-CERT")}[mismatch]
        rows[binary][field] = value
        return rows

    monkeypatch.setattr(validation, "_read_windows_info", provider)
    with pytest.raises(ValueError):
        validation.validate_artifacts({"version": VERSION, "product_name": PRODUCT}, portable, installer)


@pytest.mark.parametrize("member", ["../outside.exe", "C:/outside.exe", "user_data/history.json", "installed.marker", "ELECTROCHEM.EXE"])
def test_portable_zip_rejects_unsafe_data_and_duplicate_members(tmp_path, member):
    portable = tmp_path / f"ElectroChem-{VERSION}-win64.zip"
    installer = tmp_path / f"ElectroChem-Setup-{VERSION}.exe"
    _archive(portable, extra=(member,))
    installer.write_bytes(b"installer")
    _checksum(installer)
    with pytest.raises(ValueError):
        validation.validate_artifacts({"version": VERSION, "product_name": PRODUCT}, portable, installer)


def test_changelog_extracts_exact_version_and_preserves_subheadings():
    changelog = "## 7.0.10\nWrong patch\n## 7.0.1-rc.1\nWrong prerelease\n## 7.0.1\n\n### Features\nChosen notes\n## 6.0.20\nOld notes"
    assert validation.extract_release_notes(changelog, VERSION) == "### Features\nChosen notes"
    assert validation.extract_release_notes("## [7.0.1] - 2026-09-08\nChosen", VERSION) == "Chosen"


@pytest.mark.parametrize("changelog", ["## 7.0.10\nWrong", "## 7.0.1-rc.1\nWrong", "## 7.0.1\n", "## 7.0.1\nOne\n## 7.0.1\nTwo"])
def test_changelog_does_not_fall_back_to_nearby_or_ambiguous_versions(changelog):
    with pytest.raises(ValueError):
        validation.extract_release_notes(changelog, VERSION)


@pytest.fixture
def offline_release(tmp_path, monkeypatch):
    portable = tmp_path / f"ElectroChem-{VERSION}-win64.zip"
    installer = tmp_path / f"ElectroChem-Setup-{VERSION}.exe"
    installer.write_bytes(b"standard installer fixture")
    _checksum(installer)
    offline, runtime = _offline_artifacts(portable, installer)
    monkeypatch.setattr(validation, "_read_windows_info", _verified_windows_info)
    monkeypatch.setattr(validation, "_read_webview2_info", _runtime_metadata)
    return {"version": VERSION, "product_name": PRODUCT}, portable, installer, offline, runtime


def test_optional_offline_assets_validate_same_publisher_runtime_and_dependency_hashes(offline_release):
    source, portable, installer, offline, runtime = offline_release
    report = validation.validate_artifacts(source, portable, installer, offline_installer=offline, webview2_installer=runtime)
    assert len(report["signed_executables"]) == 4
    assert report["offline_runtime"] == _runtime_metadata(runtime)
    assert set(report["dependency_manifests"]) == {installer.name + ".dependencies.json", offline.name + ".dependencies.json"}
    assert offline.name in report["sha256"]
    # New standard builds also check their inventory without requiring an offline artifact.
    standard = validation.validate_artifacts(source, portable, installer)
    assert standard["offline_runtime"] is None
    assert standard["dependency_manifests"] == [installer.name + ".dependencies.json"]


@pytest.mark.parametrize("mismatch", ["signature", "version", "product", "signer"])
def test_offline_binary_has_same_identity_and_signing_gates(offline_release, monkeypatch, mismatch):
    source, portable, installer, offline, runtime = offline_release

    def provider(paths):
        rows = _verified_windows_info(paths)
        field, value = {"signature": ("signature", "NotSigned"), "version": ("version", "7.0.2"),
                        "product": ("product_name", "Other"), "signer": ("signer", "OTHER-CERT")}[mismatch]
        rows[-1][field] = value
        return rows

    monkeypatch.setattr(validation, "_read_windows_info", provider)
    with pytest.raises(ValueError):
        validation.validate_artifacts(source, portable, installer, offline_installer=offline, webview2_installer=runtime)


@pytest.mark.parametrize("mismatch", ["checksum", "version", "variant", "installer-hash", "runtime-version", "runtime-signer",
                                     "runtime-hash", "runtime-bundled", "dependency-hash", "dependency-missing", "dependency-path",
                                     "dependency-duplicate", "requirements", "platform"])
def test_offline_manifest_cannot_replace_verified_release_facts(offline_release, mismatch):
    source, portable, installer, offline, runtime = offline_release
    path = Path(str(offline) + ".dependencies.json")
    manifest = json.loads(path.read_text())
    if mismatch == "checksum":
        path.write_text("{}")  # Preserve the old checksum intentionally.
    else:
        if mismatch == "version":
            manifest["applicationVersion"] = "7.0.2"
        elif mismatch == "variant":
            manifest["variant"] = "standard"
        elif mismatch == "installer-hash":
            manifest["installer"]["sha256"] = "f" * 64
        elif mismatch == "runtime-version":
            manifest["prerequisites"]["webview2"]["installer"]["version"] = "1.3.4.5"
        elif mismatch == "runtime-signer":
            manifest["prerequisites"]["webview2"]["installer"]["signature"]["thumbprint"] = "UNTRUSTED"
        elif mismatch == "runtime-hash":
            manifest["prerequisites"]["webview2"]["installer"]["sha256"] = "f" * 64
        elif mismatch == "runtime-bundled":
            manifest["prerequisites"]["webview2"]["bundled"] = False
        elif mismatch == "dependency-hash":
            manifest["dependencyFiles"][0]["sha256"] = "f" * 64
        elif mismatch == "dependency-missing":
            manifest["dependencyFiles"] = []
        elif mismatch == "dependency-path":
            manifest["dependencyFiles"][0]["path"] = "../unrelated.dll"
        elif mismatch == "dependency-duplicate":
            manifest["dependencyFiles"].append(manifest["dependencyFiles"][0])
        elif mismatch == "requirements":
            manifest["runtimeRequirements"] = ["not the packaged requirements"]
        elif mismatch == "platform":
            manifest["platform"]["architecture"] = "arm64"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        _checksum(path)
    with pytest.raises(ValueError):
        validation.validate_artifacts(source, portable, installer, offline_installer=offline, webview2_installer=runtime)


def test_offline_assets_require_original_runtime_and_both_manifests(offline_release, monkeypatch):
    source, portable, installer, offline, runtime = offline_release
    for kwargs in ({"offline_installer": offline}, {"webview2_installer": runtime}):
        with pytest.raises(ValueError, match="supplied together"):
            validation.validate_artifacts(source, portable, installer, **kwargs)
    Path(str(installer) + ".dependencies.json").unlink()
    with pytest.raises(ValueError, match="missing or empty"):
        validation.validate_artifacts(source, portable, installer, offline_installer=offline, webview2_installer=runtime)
    _dependency_manifest(installer, portable)

    def rejected_runtime(_path):
        raise ValueError("Microsoft signature or payload was rejected")

    monkeypatch.setattr(validation, "_read_webview2_info", rejected_runtime)
    with pytest.raises(ValueError, match="Microsoft signature"):
        validation.validate_artifacts(source, portable, installer, offline_installer=offline, webview2_installer=runtime)


def test_offline_publish_script_validates_optional_assets_before_any_ref_write(release_repo):
    _checkout, remote, before, _expected, (portable, installer), publish = release_repo
    offline, runtime = _offline_artifacts(portable, installer)
    result = publish(verify_only=True, offline=offline, runtime=runtime)
    assert result.returncode == 0, result.stdout + result.stderr
    assert offline.name in json.loads(result.stdout)["sha256"]
    assert publish(offline=offline).returncode != 0
    offline.write_bytes(b"changed after signing and checksum")
    assert publish(offline=offline, runtime=runtime).returncode != 0
    assert _git(remote, "rev-parse", "refs/heads/main") == before
    assert _git(remote, "tag", "--list") == ""


def test_offline_workflow_is_explicit_and_keeps_review_and_signing_gates():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    option = workflow.split("      include_offline:", 1)[1].split("permissions:", 1)[0]
    assert "type: boolean" in option and "default: false" in option
    offline = workflow.split("      - name: Build optional offline installer", 1)[1].split("      - name:", 1)[0]
    assert "if: ${{ inputs.include_offline }}" in offline
    assert "https://go.microsoft.com/fwlink/?linkid=2124701" in offline
    assert "$env:RUNNER_TEMP" in offline and "-RequireSigning" in offline
    assert "-ExpectedCommit $env:EXPECTED_COMMIT" in workflow
    assert "-VerifyOnly -VerifyRemoteTag @optional" in workflow
    assert "steps.offline.outputs.MANIFEST_CHECKSUM_PATH" in workflow
