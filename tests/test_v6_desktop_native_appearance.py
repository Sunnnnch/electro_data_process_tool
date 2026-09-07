"""Validate native theme values, Windows ABI and accessibility fallback."""

from __future__ import annotations

import ctypes
from types import SimpleNamespace

import pytest

from electrochem_v6.desktop import native
from electrochem_v6.desktop.bridge import DesktopBridge

THEME = {"dark": True, "caption_color": "#102C3C", "text_color": "#EDF2F7", "high_contrast": False}


class NativeFunction:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


def mock_dwm(monkeypatch, unsupported=()):
    calls = []
    redraws = []

    def set_attribute(handle, attribute, pointer, size):
        value = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32)).contents.value
        calls.append((handle.value, attribute, value, size))
        return -2147024809 if attribute in unsupported else 0

    monkeypatch.setattr(native.ctypes, "windll", SimpleNamespace(
        dwmapi=SimpleNamespace(DwmSetWindowAttribute=NativeFunction(set_attribute)),
        user32=SimpleNamespace(RedrawWindow=NativeFunction(lambda *args: redraws.append(args) or 1)),
    ), raising=False)
    return calls, redraws


def test_native_caption_uses_colorref_byte_order_and_pointer_sized_window_handle(monkeypatch):
    calls, redraws = mock_dwm(monkeypatch)
    handle = 0x12345678ABCDEF
    result = native.apply_dwm_appearance(handle, THEME)
    assert calls == [(handle, 20, 1, 4), (handle, 35, 0x3C2C10, 4), (handle, 36, 0xF7F2ED, 4)]
    assert result["status"] == "success"
    assert all(result["applied"].values())
    assert redraws[0][0].value == handle
    assert redraws[0][3] & 0x0400  # RDW_FRAME refreshes native caption buttons.


@pytest.mark.parametrize("requested,system", [(True, False), (False, True)])
def test_high_contrast_restores_windows_caption_defaults(monkeypatch, requested, system):
    calls, _ = mock_dwm(monkeypatch)
    result = native.apply_dwm_appearance(42, {**THEME, "high_contrast": requested}, system_high_contrast=system)
    assert [call[2] for call in calls] == [0, 0xFFFFFFFF, 0xFFFFFFFF]
    assert result["high_contrast"] is True


@pytest.mark.parametrize("unsupported", [(35, 36), (20, 35, 36)])
def test_unsupported_windows_attributes_do_not_block_other_attributes(monkeypatch, unsupported):
    calls, _ = mock_dwm(monkeypatch, unsupported)
    result = native.apply_dwm_appearance(42, THEME)
    assert len(calls) == 3
    assert result["applied"] == {"dark": 20 not in unsupported, "caption_color": False, "text_color": False}
    assert result["status"] == ("unsupported" if 20 in unsupported else "success")


@pytest.mark.parametrize("key,value", [("dark", "false"), ("high_contrast", 1),
                                      ("caption_color", "url(file:///private)"),
                                      ("text_color", "#fff"), ("text_color", 0)])
def test_bridge_appearance_values_are_strict(key, value):
    with pytest.raises(ValueError):
        native.clean_window_appearance({**THEME, key: value})


def test_native_appearance_bridge_remains_confined_to_workbench():
    appearances = []
    window = SimpleNamespace(get_current_url=lambda: "http://127.0.0.1:8123/ui?desktop=1")
    app = SimpleNamespace(window=window, ui_url="http://127.0.0.1:8123/ui?desktop=1",
                          set_window_appearance=lambda value: appearances.append(value) or {"status": "success"})
    bridge = DesktopBridge(app)
    assert bridge.set_window_appearance(THEME)["status"] == "success"
    window.get_current_url = lambda: "https://example.org/"
    with pytest.raises(ValueError, match="local workbench"):
        bridge.set_window_appearance(THEME)
    assert appearances == [THEME]
