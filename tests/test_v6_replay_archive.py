import hashlib
import shutil
import zipfile
from pathlib import Path

import pytest

from electrochem_v6.core.replay_archive import restore_uploaded_sources


@pytest.fixture
def archive_recipe(tmp_path, monkeypatch):
    monkeypatch.setenv("ELECTROCHEM_V6_DATA_DIR", str(tmp_path / "runtime"))
    archive = tmp_path / "original.zip"
    files = {"sample/LSV_a.txt": b"0 0\n1 0.01\n", "sample/EIS_a.txt": b"1000 2 -1\n"}
    with zipfile.ZipFile(archive, "w") as zipped:
        for name, content in files.items():
            zipped.writestr(name, content)
    inputs = [{"path": str(tmp_path / "gone" / name), "file_name": Path(name).name,
               "archive_member": name, "sha256": hashlib.sha256(content).hexdigest()}
              for name, content in files.items()]
    return {"source_archive_path": str(archive), "source_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "inputs": inputs}


def test_restore_preserves_structure_and_reuses_verified_cache_without_archive(archive_recipe):
    restored = restore_uploaded_sources(archive_recipe, archive_recipe["inputs"])
    assert len(restored["source_paths"]) == 2
    folder = Path(restored["folder_path"])
    assert (folder / "sample/LSV_a.txt").read_bytes() == b"0 0\n1 0.01\n"
    Path(archive_recipe["source_archive_path"]).unlink()
    again = restore_uploaded_sources(archive_recipe, archive_recipe["inputs"])
    assert again["source_paths"] == restored["source_paths"]


def test_restore_respects_user_relocation_and_does_not_replace_existing_sources(archive_recipe):
    inputs = archive_recipe["inputs"]
    existing = Path(inputs[0]["path"])
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"changed by user")
    result = restore_uploaded_sources(archive_recipe, inputs, relocations={inputs[1]["path"]: "selected.txt"})
    assert result["source_paths"] == {}
    assert existing.read_bytes() == b"changed by user"


@pytest.mark.parametrize("failure", ["changed_zip", "missing_zip", "missing_hash", "changed_member", "illegal_member", "traversal_zip", "size_limit"])
def test_restore_rejects_unverifiable_or_unsafe_archives(archive_recipe, failure, monkeypatch, tmp_path):
    archive = Path(archive_recipe["source_archive_path"])
    if failure == "changed_zip":
        with zipfile.ZipFile(archive, "a") as zipped:
            zipped.writestr("new.txt", "new")
    elif failure == "missing_zip":
        archive.unlink()
    elif failure == "missing_hash":
        archive_recipe["source_archive_sha256"] = None
    elif failure == "changed_member":
        archive_recipe["inputs"][0]["sha256"] = "0" * 64
    elif failure == "illegal_member":
        archive_recipe["inputs"][0]["archive_member"] = "../escape.txt"
    elif failure == "traversal_zip":
        with zipfile.ZipFile(archive, "a") as zipped:
            zipped.writestr("../escape.txt", "bad")
        archive_recipe["source_archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    elif failure == "size_limit":
        monkeypatch.setenv("ELECTROCHEM_V6_MAX_ZIP_UNCOMP_BYTES", "1")
    with pytest.raises(ValueError):
        restore_uploaded_sources(archive_recipe, archive_recipe["inputs"])
    assert not (tmp_path / "escape.txt").exists()
    assert not list((tmp_path / "runtime/runs/replay_sources").glob("restore_*"))


def test_cache_tampering_is_not_accepted_as_original_input(archive_recipe):
    restored = restore_uploaded_sources(archive_recipe, archive_recipe["inputs"])
    Path(next(iter(restored["source_paths"].values()))).write_text("tampered")
    with pytest.raises(ValueError, match="指纹不符"):
        restore_uploaded_sources(archive_recipe, archive_recipe["inputs"])


def test_removed_data_subtree_can_be_restored_without_replacing_cache_siblings(archive_recipe):
    restored = restore_uploaded_sources(archive_recipe, archive_recipe["inputs"])
    folder = Path(restored["folder_path"]).resolve()
    sibling = folder.parent / "retained.txt"
    sibling.write_text("keep")
    assert folder.name == "data" and folder.parent.name == archive_recipe["source_archive_sha256"]
    shutil.rmtree(folder)
    again = restore_uploaded_sources(archive_recipe, archive_recipe["inputs"])
    assert again["source_paths"] == restored["source_paths"]
    assert sibling.read_text() == "keep"
