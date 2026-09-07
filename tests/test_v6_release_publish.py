"""Exercise exact source/asset gates and atomic pushes against disposable local Git only."""

from __future__ import annotations

import hashlib
import importlib.util
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

    def publish(*, target_branch="main", verify_only=False, expected_commit=expected):
        arguments = [shell, "-NoProfile", "-NonInteractive", "-File", str(packaging / PUBLISH.name),
                     "-Tag", TAG, "-ExpectedCommit", expected_commit, "-PortableZip", str(portable),
                     "-Installer", str(installer), "-PythonPath", sys.executable]
        if target_branch:
            arguments.extend(["-TargetBranch", target_branch])
        if verify_only:
            arguments.append("-VerifyOnly")
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
