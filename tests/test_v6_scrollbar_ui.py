"""Theme scrollbars on the real document, project list, help and assistant scrollers."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from electrochem_v6.store.projects import create_project
from test_v6_appearance_ui import appearance_browser as appearance_browser
from test_v6_assistant_appearance_ui import REPLY, _contrast


def _assert_scrollbar(page, selector, *, viewport=False):
    state = page.locator(selector).first.evaluate("""(node, viewport) => {
      const style = getComputedStyle(node);
      const color = value => { const probe = document.createElement('i'); probe.style.color=value;
        node.appendChild(probe); const result=getComputedStyle(probe).color; probe.remove(); return result; };
      return {colors:style.scrollbarColor, width:style.scrollbarWidth,
        thumb:color(style.getPropertyValue('--scrollbar-thumb')),
        track:color(style.getPropertyValue(viewport ? '--scrollbar-page-track' : '--scrollbar-track'))};
    }""", viewport)
    colors = re.findall(r"rgb\([^)]+\)", state["colors"])
    assert colors == [state["thumb"], state["track"]], (selector, state)
    assert state["width"] == "auto"
    assert _contrast(*colors) >= 3, (selector, colors)


@pytest.mark.parametrize("theme", ["lab", "dark", "ocean", "pixel"])
def test_scrollbars_theme_all_real_scrollers_and_forced_colors(appearance_browser, theme):
    for index in range(30):
        create_project(f"Scrollbar project {index:02d}")
    page = appearance_browser(width=600)
    page.evaluate("theme => ElectrochemTheme.update({theme})", theme)
    page.click("#tab-btn-project")
    project_list = page.locator("#project-list")
    assert project_list.evaluate("node => node.scrollHeight > node.clientHeight")
    _assert_scrollbar(page, "html", viewport=True)
    _assert_scrollbar(page, "#project-list")
    project_list.hover()
    page.mouse.wheel(0, 420)
    page.wait_for_function("() => document.querySelector('#project-list').scrollTop > 0")

    page.click("#help-docs-btn")
    page.wait_for_function("() => document.querySelector('#help-doc-body').textContent.length > 1000")
    help_scroll = page.locator("#help-doc-scroll")
    assert help_scroll.evaluate("node => node.scrollHeight > node.clientHeight")
    _assert_scrollbar(page, "#help-doc-scroll")
    help_scroll.hover()
    page.mouse.wheel(0, 350)
    page.wait_for_function("() => document.querySelector('#help-doc-scroll').scrollTop > 0")
    page.keyboard.press("Escape")

    page.click("#assistant-fab")
    page.evaluate("messages => renderMessages(messages)", [{"role": "agent", "content": REPLY * 4}])
    page.evaluate("document.querySelector('#chat-log').scrollTop = 0")
    assert page.locator("#chat-log").evaluate("node => node.scrollHeight > node.clientHeight")
    code = page.locator(".msg.agent pre").first
    assert code.evaluate("node => node.scrollWidth > node.clientWidth")
    _assert_scrollbar(page, "#chat-log")
    _assert_scrollbar(page, ".msg.agent pre")
    code.focus()
    code.press("ArrowRight")
    page.wait_for_function("() => document.querySelector('.msg.agent pre').scrollLeft > 0")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")

    output = Path(__file__).resolve().parents[1] / ".test_runtime" / "scrollbars"
    output.mkdir(parents=True, exist_ok=True)
    page.locator("#assistant-drawer").screenshot(path=str(output / f"assistant-scrollbars-{theme}.png"))
    page.emulate_media(forced_colors="active")
    page.wait_for_function("() => matchMedia('(forced-colors: active)').matches")
    for selector in ("html", "#project-list", "#help-doc-scroll", "#chat-log", ".msg.agent pre"):
        assert page.locator(selector).first.evaluate("node => getComputedStyle(node).scrollbarColor") == "auto"
    page.emulate_media(forced_colors="none")
    _assert_scrollbar(page, "#chat-log")
