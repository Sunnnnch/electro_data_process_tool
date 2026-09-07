"""All install paths include the runtime readers and share production requirements."""

import sys
from pathlib import Path

from packaging.requirements import Requirement

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def _requirements(path):
    return {
        Requirement(line).name: Requirement(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith(("#", "-"))
    }


def test_runtime_package_and_frozen_build_share_requirements():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["setuptools"]["dynamic"]["dependencies"]["file"] == ["requirements.txt"]
    prod = _requirements(ROOT / "requirements.txt")
    frozen_file = ROOT / "requirements-frozen.txt"
    assert "-r requirements.txt" in frozen_file.read_text(encoding="utf-8")
    frozen = _requirements(frozen_file)
    assert set(prod) == set(frozen)
    for name, requirement in frozen.items():
        pins = list(requirement.specifier)
        assert len(pins) == 1 and pins[0].operator == "=="
        assert prod[name].specifier.contains(pins[0].version)
    assert "xlrd" in prod
    assert "openpyxl" in prod
    packaging = (ROOT / "packaging" / "requirements-pack.txt").read_text(encoding="utf-8")
    assert "-r ../requirements-frozen.txt" in packaging
    build_tools = _requirements(ROOT / "packaging" / "requirements-pack.txt")
    assert set(build_tools) == {"pyinstaller", "pip"}
    for requirement in build_tools.values():
        pins = list(requirement.specifier)
        assert len(pins) == 1 and pins[0].operator == "=="
