"""Validate the shipped icon resources and stable package-relative identity."""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
from pathlib import Path

import pytest
from PIL import Image

from electrochem_v6.desktop import branding

ROOT = Path(__file__).resolve().parents[1]
SIZES = {16, 20, 24, 32, 40, 48, 64, 128, 256}


def test_selected_png_is_unchanged_in_desktop_and_web_resources():
    selected = ROOT / "design/icon-concepts/2026-09-08/D-intelligent-data.png"
    original = selected.read_bytes()
    assert branding.icon_path("png").read_bytes() == original
    assert (ROOT / "src/electrochem_v6/ui/static/app_icon.png").read_bytes() == original
    with Image.open(selected) as image:
        assert image.format == "PNG"
        assert image.width == image.height


def test_installer_and_desktop_icons_match_and_all_frames_decode():
    desktop = branding.icon_path()
    installer = ROOT / "packaging/assets/app_icon.ico"
    assert hashlib.sha256(desktop.read_bytes()).digest() == hashlib.sha256(installer.read_bytes()).digest()
    # Independent image decoder validates the actual multi-frame file, including
    # 256px (encoded with zero dimension bytes by the ICO container standard).
    with Image.open(desktop) as image:
        assert image.format == "ICO"
        ico = getattr(image, "ico")
        assert ico.sizes() == {(size, size) for size in SIZES}
        for size in SIZES:
            frame = ico.getimage((size, size))
            frame.load()
            assert frame.size == (size, size)
            assert frame.mode == "RGBA"
            assert frame.getbbox() is not None
            assert frame.getchannel("A").getextrema() == (0, 255)


def test_branding_uses_relocated_package_assets_without_checkout_or_working_directory(tmp_path, monkeypatch):
    assert branding.APP_USER_MODEL_ID == "ElectroChem.Desktop"
    package = tmp_path / "bundle" / "electrochem_v6" / "desktop"
    shutil.copytree(branding.icon_path().parent, package / "assets")
    module_path = package / "branding.py"
    shutil.copy2(branding.__file__, module_path)
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.spec_from_file_location("isolated_desktop_branding", module_path)
    assert spec and spec.loader
    relocated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(relocated)
    assert relocated.APP_USER_MODEL_ID == branding.APP_USER_MODEL_ID
    assert relocated.icon_path() == package / "assets" / "app_icon.ico"
    assert relocated.icon_path(".PNG") == package / "assets" / "app_icon.png"
    assert relocated.icon_path().is_file()


@pytest.mark.parametrize("suffix", ["svg", "../png", "png/../../secrets"])
def test_icon_resource_rejects_unsupported_formats(suffix):
    with pytest.raises(ValueError, match="ico or png"):
        branding.icon_path(suffix)
