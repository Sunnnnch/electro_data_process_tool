"""Regression tests for release tag selection and least-privilege CI permissions."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_ci_is_read_only_and_does_not_calculate_or_publish_versions():
    workflow = _workflow("ci.yml")

    assert re.search(r"(?m)^permissions:\s*\n  contents: read$", workflow)
    assert "contents: write" not in workflow
    assert "semantic_release" not in workflow and "git push" not in workflow
    assert "action-gh-release" not in workflow
    assert 'python-version: ["3.10", "3.12"]' in workflow


def test_manual_release_resolves_and_checks_out_a_real_version_tag():
    workflow = _workflow("release.yml")

    assert "github.ref_name" not in workflow
    assert "git tag --sort" not in workflow
    assert "expected_commit:" in workflow
    assert workflow.count("required: true") == 2
    assert 'git rev-parse --verify "refs/tags/$tag^{commit}"' in workflow
    assert "git checkout --detach $expected" in workflow
    assert "Invalid release tag" in workflow
    assert "--source-only --verify-remote-tag" in workflow
    assert "target_commitish: ${{ steps.version.outputs.COMMIT }}" in workflow


def test_release_publication_is_after_build_signing_and_artifact_validation():
    workflow = _workflow("release.yml")
    publish = workflow.index("- name: Verify release artifacts")
    assert workflow.index("- name: Build portable") < publish
    assert workflow.index("- name: Sign portable executables") < publish
    assert workflow.index("- name: Build installer") < publish
    assert publish < workflow.index("- name: Create GitHub Release")
    assert "git push" not in workflow
    for name in ("release.yml",):
        content = _workflow(name)
        assert "group: electrochem-windows-release" in content
        assert "cancel-in-progress: false" in content
        assert "fail_on_unmatched_files: true" in content


def test_manual_release_installs_required_installer_and_checks_artifacts():
    workflow = _workflow("release.yml")
    assert workflow.index("- name: Install Inno Setup") < workflow.index("- name: Build installer")
    assert workflow.index("- name: Verify release artifacts") < workflow.index("- name: Create GitHub Release")
    assert "-VerifyOnly" in workflow
    assert "-VerifyRemoteTag" in workflow


def test_ci_and_release_require_browser_and_sdk_tests_instead_of_skipping():
    for name in ("ci.yml", "release.yml"):
        workflow = _workflow(name)
        assert 'ELECTROCHEM_REQUIRE_PLAYWRIGHT: "1"' in workflow
        assert "python -m playwright install chromium" in workflow
        assert "from mcp.server.fastmcp import FastMCP" in workflow
        assert "python -m pytest tests/" in workflow
        assert "continue-on-error" not in workflow


def test_release_does_not_overwrite_an_already_public_asset_set():
    workflow = _workflow("release.yml")
    assert workflow.count("if (!release.data.draft) throw new Error") == 2
    assert workflow.index("- name: Reject an already published version") < workflow.index("- name: Build portable")
    assert workflow.index("- name: Verify release artifacts") < workflow.index("- name: Recheck publication state")
    assert workflow.index("- name: Recheck publication state") < workflow.index("- name: Create GitHub Release")
    assert "--print-notes" in workflow
