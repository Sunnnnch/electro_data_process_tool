"""Assistant reading contrast, theme changes, and local overflow in the actual UI."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from test_v6_project_recovery_ui import recovery_browser as recovery_browser

REPLY = """## 测量结果与拟合依据
这组样品应先核对电极面积与参比电极换算，再比较拟合结果。保留原始测量点，避免把复算版本计作独立实验。

> 当前拟合只适用于所选区间，不能据此推断其他电位范围。

- 电流密度：`10 mA/cm²`
- 电位换算：E_RHE = E_measured + E_reference + 0.0591 × pH
- [查看实验说明](https://example.org/measurement)

```text
sample_A: E_RHE = E_measured + E_reference + 0.0591 * pH; source=independent_experiment; current_density_mA_cm2=10; verify_electrode_area_before_comparison
```

本段用于验证长分析答案。数据来源、单位、筛选条件和拟合范围都应保留在结果附近，以便重新核对。
"""


def _render(page, manager, theme="lab"):
    page.goto(f"http://127.0.0.1:{manager.port}/ui", wait_until="networkidle")
    page.evaluate("theme => window.ElectrochemTheme.save(theme)", theme)
    page.click("#assistant-fab")
    page.evaluate("messages => renderMessages(messages)", [
        {"role": "user", "content": "请检查这组数据的拟合依据，并准备参数建议。", "timestamp": "2026-09-07 18:00"},
        {"role": "agent", "content": REPLY, "timestamp": "2026-09-07 18:01", "metadata": {
            "context_usage": {"professional_mode": True, "database": True},
            "pending_approvals": [{"approval_id": "appearance-review", "summary": "按已确认面积复算所选样品",
                "expires_at_epoch_ms": 18000000000000, "details": {"area": "1 cm²", "source": "独立实验"}}],
            "action_cards": [{"schema_version": 1, "id": "appearance-card", "kind": "report_records",
                "project_id": "appearance-project", "project_name": "样品对比项目", "record_keys": ["record-a"]}],
        }},
    ])


def _rgb(value):
    numbers = [float(number) for number in re.findall(r"[\d.]+", value)]
    assert len(numbers) >= 3, value
    return numbers[:3]


def _contrast(foreground, background):
    def luminance(value):
        channels = [channel / 255 for channel in _rgb(value)]
        channels = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
        return sum(channel * weight for channel, weight in zip(channels, (0.2126, 0.7152, 0.0722)))

    values = sorted([luminance(foreground), luminance(background)])
    return (values[1] + 0.05) / (values[0] + 0.05)


def _colors(page, selector):
    return page.locator(selector).first.evaluate("""el => {
      const color = getComputedStyle(el).color;
      let node = el;
      while (node && getComputedStyle(node).backgroundColor === 'rgba(0, 0, 0, 0)') node = node.parentElement;
      return [color, node ? getComputedStyle(node).backgroundColor : 'rgb(255, 255, 255)'];
    }""")


def _screenshot_directory(source):
    output = Path(os.environ.get("ELECTROCHEM_ASSISTANT_SCREENSHOT_DIR") or source.parent.parent)
    output.mkdir(parents=True, exist_ok=True)
    return output


@pytest.mark.parametrize("theme", ["lab", "dark", "ocean", "pixel"])
def test_assistant_reading_and_confirmation_contrast_in_every_theme(recovery_browser, theme):
    page, manager, _payload, _source, _errors = recovery_browser
    _render(page, manager, theme)
    for selector in (
        ".msg.user .content", ".msg.agent .content", ".msg.agent .meta", ".msg .content blockquote",
        ".msg .content a", ".msg .content pre code", ".msg-source-badge", ".msg-approval-title",
        ".msg-approval-summary", ".msg-approval-warning", ".msg-approval-detail-row strong",
        ".assistant-action-card", ".assistant-quick-btn", ".assistant-approval-btn.approve", ".assistant-approval-btn.decline",
    ):
        assert _contrast(*_colors(page, selector)) >= 4.5, (theme, selector, _colors(page, selector))

    content = page.locator(".msg.agent .content")
    font = content.evaluate("el => [parseFloat(getComputedStyle(el).fontSize), parseFloat(getComputedStyle(el).lineHeight)]")
    assert font[0] >= 15
    assert font[1] / font[0] >= 1.65
    widths = page.evaluate("""() => ({
      agent: document.querySelector('.msg.agent').getBoundingClientRect().width,
      user: document.querySelector('.msg.user').getBoundingClientRect().width,
      log: document.querySelector('#chat-log').clientWidth,
    })""")
    assert widths["agent"] > widths["user"]
    assert widths["agent"] >= widths["log"] - 28

    approve = page.locator(".assistant-approval-btn.approve")
    approve.hover()
    assert _contrast(*_colors(page, ".assistant-approval-btn.approve")) >= 4.5
    approve.focus()
    page.keyboard.press("Tab")
    page.keyboard.press("Shift+Tab")
    assert approve.evaluate("el => document.activeElement === el")
    outline = approve.evaluate("el => getComputedStyle(el).outlineStyle")
    assert outline != "none"
    approve.evaluate("el => el.disabled = true")
    assert approve.is_disabled()
    assert approve.evaluate("el => getComputedStyle(el).cursor") == "not-allowed"
    page.locator(".msg-approval").evaluate("el => el.classList.add('expired')")
    assert _contrast(*_colors(page, ".msg-approval-summary")) >= 4.5

    page.set_viewport_size({"width": 600, "height": 900})
    page.evaluate("() => document.querySelector('#chat-log').scrollTop = 0")
    assert page.locator("#assistant-drawer").evaluate("el => el.getBoundingClientRect().right <= innerWidth")
    assert page.locator("#chat-log").evaluate("el => el.scrollWidth <= el.clientWidth + 1")
    output = _screenshot_directory(_source)
    page.locator("#assistant-drawer").screenshot(path=str(output / f"assistant-{theme}-600.png"))
    if os.environ.get("ELECTROCHEM_ASSISTANT_SCREENSHOT_DIR"):
        page.locator(".msg .content pre").scroll_into_view_if_needed()
        page.locator("#assistant-drawer").screenshot(path=str(output / f"assistant-{theme}-code-600.png"))


def test_assistant_font_density_changes_preserve_content_and_keyboard_overflow(recovery_browser):
    page, manager, _payload, _source, _errors = recovery_browser
    _render(page, manager, "dark")
    original = page.locator(".msg.agent .content").inner_text()
    observed = []
    for size, expected in (("standard", 15), ("large", 17), ("extra-large", 19)):
        page.evaluate("fontSize => ElectrochemTheme.update({fontSize})", size)
        for density in ("comfortable", "compact"):
            page.evaluate("density => ElectrochemTheme.update({density})", density)
            metrics = page.locator(".msg.agent .content").evaluate("el => [parseFloat(getComputedStyle(el).fontSize), parseFloat(getComputedStyle(el).lineHeight)]")
            assert metrics[0] == expected
            assert metrics[1] / metrics[0] == pytest.approx(1.7 if density == "comfortable" else 1.55, abs=0.01)
            assert page.locator(".msg.agent .content").inner_text() == original
        observed.append(metrics[0])
    assert observed == [15, 17, 19]

    page.set_viewport_size({"width": 600, "height": 900})
    code = page.locator(".msg .content pre")
    assert code.get_attribute("tabindex") == "0"
    code.focus()
    assert code.evaluate("el => el.scrollWidth > el.clientWidth")
    code.press("ArrowRight")
    page.wait_for_function("() => document.querySelector('.msg .content pre').scrollLeft > 0")
    assert code.evaluate("el => getComputedStyle(el).outlineStyle") != "none"

    # The current Markdown parser renders formulas as text. Table-capable
    # renderers and action previews must also retain keyboard-accessible columns.
    page.evaluate("""() => {
      const headers = Array.from({length:24}, (_, index) => '<th>样品 ' + (index + 1) + '</th>').join('');
      const cells = Array.from({length:24}, () => '<td>10 mA/cm²</td>').join('');
      const table = '<table><thead><tr>' + headers + '</tr></thead><tbody><tr>' + cells + '</tr></tbody></table>';
      const rendered = ElectrochemAssistantPage.renderMessageItem({role:'agent', lang:'zh', content:table, renderAgentContent:value=>value});
      document.querySelector('#chat-log').insertAdjacentHTML('beforeend', rendered);
    }""")
    region = page.locator(".assistant-table-scroll")
    assert region.get_attribute("role") == "region"
    assert "横向滚动" in region.get_attribute("aria-label")
    assert region.locator("table").inner_text().count("10 mA/cm²") == 24
    cell = region.locator("td").first.bounding_box()
    assert cell is not None
    assert cell["width"] >= 80, "Scientific table columns must not shrink to one-character vertical stacks"
    assert cell["height"] < 80, "A short measurement and its unit should fit within two readable lines"
    assert page.locator("#chat-log").evaluate("el => el.scrollWidth <= el.clientWidth + 1")
    assert page.locator(".msg.agent").last.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
    region.focus()
    assert region.evaluate("el => getComputedStyle(el).outlineStyle") != "none"
    assert region.evaluate("el => el.scrollWidth > el.clientWidth")
    region.press("ArrowRight")
    page.wait_for_function("() => document.querySelector('.assistant-table-scroll').scrollLeft > 0")
    if os.environ.get("ELECTROCHEM_ASSISTANT_SCREENSHOT_DIR"):
        region.evaluate("el => el.scrollLeft = 0")
        output = _screenshot_directory(_source)
        for theme in ("lab", "dark", "pixel"):
            page.evaluate("theme => ElectrochemTheme.save(theme)", theme)
            region.scroll_into_view_if_needed()
            page.locator("#assistant-drawer").screenshot(path=str(output / f"assistant-{theme}-wide-table-600.png"))
