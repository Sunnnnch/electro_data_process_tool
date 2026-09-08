"""Regression tests for release tag selection and least-privilege CI permissions."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("step", ["Reject an already published version", "Recheck publication state before uploading"])
@pytest.mark.parametrize("release, accepted", [
    ({"draft": True, "assets": [{"name": "ElectroChem-Setup-7.0.1-offline.exe"}]}, False),
    ({"draft": True, "assets": []}, True),
    ({"draft": False, "assets": []}, False),
    ({"missing": True}, True),
])
def test_release_publication_gates_reject_nonempty_drafts_without_removing_assets(step, release, accepted):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to execute the GitHub Actions script boundary")
    section = _workflow("release.yml").split(f"      - name: {step}\n", 1)[1].split("      - name:", 1)[0]
    script = section.split("          script: |\n", 1)[1]
    script = "\n".join(line[12:] for line in script.splitlines() if line.startswith("            "))
    harness = """
      const release = JSON.parse(process.argv[1]);
      const context = {repo:{owner:'test', repo:'test'}};
      const github = {rest:{repos:{getReleaseByTag:async () => {
        if (release.missing) { const error = new Error('Not found'); error.status = 404; throw error; }
        return {data:release};
      }}}};
      (async () => {
        try { await (async () => { SCRIPT })(); process.stdout.write(JSON.stringify({ok:true, release})); }
        catch (error) { process.stdout.write(JSON.stringify({ok:false, message:error.message, release})); }
      })();
    """.replace("SCRIPT", script)
    result = subprocess.run([node, "-e", harness, json.dumps(release)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["ok"] is accepted
    assert value["release"] == release
    if release.get("draft") and release.get("assets"):
        assert "assets that this run has not verified" in value["message"]
