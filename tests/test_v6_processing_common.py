"""Tests for shared processing helpers."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from electrochem_v6.core.processing_common import (
    apply_plot_font,
    build_file_context,
    ensure_output_dir,
    format_sample_title,
    save_current_figure,
    serialized_plotting,
)


class _FakePyplot:
    def __init__(self) -> None:
        self.rcParams: dict[str, object] = {}
        self.saved: tuple[str, int, str] | None = None
        self.closed = False

    def savefig(self, image_path: str, *, dpi: int, bbox_inches: str) -> None:
        self.saved = (image_path, dpi, bbox_inches)
        Path(image_path).write_text("image", encoding="utf-8")

    def close(self) -> None:
        self.closed = True


def test_build_file_context_creates_output_dir(tmp_path):
    sample_dir = tmp_path / "sample-a"
    sample_dir.mkdir()
    output_dir = tmp_path / "out"

    ctx = build_file_context(str(sample_dir), "LSV_demo.txt", {"output_dir": str(output_dir)})

    assert ctx.filepath == str(sample_dir / "LSV_demo.txt")
    assert ctx.sample_name == "sample-a"
    assert ctx.file_stem == "LSV_demo"
    assert ctx.output_dir == str(output_dir)
    assert output_dir.exists()


def test_ensure_output_dir_uses_fallback_when_output_is_blank(tmp_path):
    fallback = tmp_path / "fallback"

    result = ensure_output_dir("", str(fallback))

    assert result == str(fallback)
    assert fallback.exists()


def test_apply_plot_font_sets_standard_matplotlib_params():
    fake = _FakePyplot()

    apply_plot_font(fake, "Microsoft YaHei")

    assert fake.rcParams["font.sans-serif"] == ["Microsoft YaHei"]
    assert fake.rcParams["axes.unicode_minus"] is False


def test_save_current_figure_creates_parent_and_closes(tmp_path):
    fake = _FakePyplot()
    image_path = tmp_path / "plots" / "demo.png"

    result = save_current_figure(fake, str(image_path), dpi=150)

    assert result == str(image_path)
    assert fake.saved == (str(image_path), 150, "tight")
    assert fake.closed is True
    assert image_path.exists()


def test_format_sample_title_supports_extra_fields_and_safe_fallback():
    assert format_sample_title("ECSA {sample} @ {Ev:.2f}", "s1", Ev=0.1) == "ECSA s1 @ 0.10"
    assert format_sample_title("LSV - {sample} - {missing}", "s1") == "LSV - s1 - {missing}"


def test_serialized_plotting_prevents_concurrent_rendering():
    start = threading.Event()
    counter_lock = threading.Lock()
    active = 0
    max_active = 0

    @serialized_plotting
    def render() -> None:
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.03)
        with counter_lock:
            active -= 1

    def invoke() -> None:
        start.wait(timeout=1)
        render()

    threads = [threading.Thread(target=invoke) for _ in range(4)]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert max_active == 1
