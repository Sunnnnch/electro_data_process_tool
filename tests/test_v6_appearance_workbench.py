"""Appearance acceptance against real workbench records, controls and task states."""

from __future__ import annotations

import json
import os
from pathlib import Path

from electrochem_v6.core.process_service import process_folder
from electrochem_v6.store.runtime import get_database
from test_v6_project_recovery_ui import recovery_browser as recovery_browser

THEMES = ("lab", "ocean", "dark", "pixel")
HEADER_ACTIONS = ("#project-use-btn", "#project-recovery-btn", "#project-more-menu > summary")

# Composite real DOM backgrounds, including alpha, rather than comparing CSS tokens.
MEASURE = """(node, placeholder) => {
  if (!node.isConnected) return null;
  const context = document.createElement('canvas').getContext('2d');
  const parse = color => {
    // Chromium may return color(srgb ...) for color-mix(). Let the browser
    // resolve every supported CSS color to the actual sRGB display channels.
    context.clearRect(0, 0, 1, 1);
    context.fillStyle = color;
    context.fillRect(0, 0, 1, 1);
    const channels = Array.from(context.getImageData(0, 0, 1, 1).data);
    channels[3] /= 255;
    return channels;
  };
  const over = (front, back) => front.slice(0, 3).map((v, i) => v * front[3] + back[i] * (1 - front[3]));
  const background = node => {
    const parents = [];
    for (let parent = node; parent; parent = parent.parentElement) parents.unshift(parent);
    let color = [255, 255, 255], unresolvedImage = false;
    parents.forEach(parent => {
      const css = getComputedStyle(parent), layer = parse(css.backgroundColor);
      if (layer[3] === 1) unresolvedImage = false;
      color = over(layer, color);
      if (css.backgroundImage !== 'none') unresolvedImage = true;
    });
    return {color, unresolvedImage};
  };
  const css = getComputedStyle(node), bg = background(node), outside = background(node.parentElement);
  let opacity = 1;
  for (let parent = node; parent; parent = parent.parentElement) opacity *= Number(getComputedStyle(parent).opacity);
  const foreground = parse(getComputedStyle(node, placeholder ? '::placeholder' : null).color);
  foreground[3] *= opacity;
  return { text: over(foreground, bg.color), background: bg.color, adjacent: outside.color,
    border: over(parse(css.borderTopColor), outside.color), unresolvedImage: bg.unresolvedImage || outside.unresolvedImage,
    borderWidth: parseFloat(css.borderTopWidth), opacity, disabled: Boolean(node.disabled),
    color: css.color, backgroundColor: css.backgroundColor, cursor: css.cursor,
    height: node.getBoundingClientRect().height, width: node.getBoundingClientRect().width };
}"""


def _contrast(first, second):
    def luminance(color):
        channels = [value / 255 for value in color]
        linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in channels]
        return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))
    values = sorted((luminance(first), luminance(second)))
    return (values[1] + .05) / (values[0] + .05)


def _check_contrast(page, selector, theme, issues, *, placeholder=False, border=False):
    node = page.locator(selector).first
    assert node.is_visible(), selector
    # The task poller may replace a card between locator resolution and read.
    value = None
    for _attempt in range(3):
        value = node.evaluate(MEASURE, placeholder)
        if value is not None:
            break
    assert value is not None, f"Control kept detaching during measurement: {selector}"
    ratio = _contrast(value["text"], value["background"])
    if ratio < 4.5:
        issues.append({"theme": theme, "selector": selector, "state": "placeholder" if placeholder else "text", "ratio": round(ratio, 3), **value})
    if border:
        edge_ratio = _contrast(value["border"], value["adjacent"])
        if value["borderWidth"] < 1 or edge_ratio < 3:
            issues.append({"theme": theme, "selector": selector, "state": "input-boundary", "ratio": round(edge_ratio, 3), **value})
    assert not value["unresolvedImage"], f"Background requires pixel sampling: {selector} {value}"
    return value


def _shot(page, name):
    folder = os.environ.get("ELECTROCHEM_APPEARANCE_SCREENSHOTS")
    if folder:
        target = Path(folder)
        target.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target / f"{name}.png"), full_page=False, animations="disabled")


def _report(name, issues):
    folder = os.environ.get("ELECTROCHEM_APPEARANCE_SCREENSHOTS")
    if folder:
        target = Path(folder)
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{name}.json").write_text(json.dumps(issues, ensure_ascii=False, indent=2), encoding="utf-8")
    assert not issues, json.dumps(issues, ensure_ascii=False, indent=2)


def _prepare(recovery_browser):
    page, manager, payload, _source, _errors = recovery_browser
    result = process_folder(payload)
    assert result["status"] == "success", result
    database = get_database()
    for status in ("succeeded", "failed", "running", "interrupted"):
        job_id = f"appearance-{status}"
        database.create_processing_job(job_id, kind="process", payload=payload)
        database.update_processing_job(job_id, status=status, current_item="处理 CV 独立实验", progress_current=1, progress_total=3,
                                       error="示例：输入列单位不一致" if status == "failed" else None,
                                       result=result if status == "succeeded" else {})
    page.goto(f"http://127.0.0.1:{manager.port}/ui", wait_until="networkidle")
    page.wait_for_function("Boolean(processParameterSchema)")
    page.click("#tab-btn-project")
    page.wait_for_selector(".project-record-check")
    page.locator(".project-record-check").first.check()
    page.locator(".project-record-open").first.click()
    page.wait_for_selector("#project-history-detail-panel:not([hidden])")
    return page, payload


def _settle_hover(node):
    node.hover()
    node.evaluate("async node => { await Promise.all(node.getAnimations().map(animation => animation.finished)); }")


def test_four_themes_have_readable_real_controls_and_task_states(recovery_browser):
    page, _payload = _prepare(recovery_browser)
    page.set_viewport_size({"width": 1440, "height": 1080})
    issues, header_heights = [], {}
    for theme in THEMES:
        page.evaluate("theme => ElectrochemTheme.update({ theme, fontSize: 'standard', density: 'comfortable' })", theme)
        page.click("#tab-btn-project")
        page.mouse.move(0, 0)
        header_heights[theme] = [page.locator(selector).evaluate("node => node.getBoundingClientRect().height") for selector in HEADER_ACTIONS]
        if max(header_heights[theme]) - min(header_heights[theme]) > 1:
            issues.append({"theme": theme, "state": "header-actions-not-equal", "heights": header_heights[theme]})
        normal = _check_contrast(page, "#project-use-btn", theme, issues)
        for selector in ("#project-use-btn", "#project-recovery-btn", "#project-more-menu > summary"):
            _check_contrast(page, selector, theme, issues)
            _settle_hover(page.locator(selector))
            _check_contrast(page, selector, theme + " hover", issues)
        disabled = _check_contrast(page, "#project-compare-records-btn", theme, issues)
        assert disabled["disabled"] and not normal["disabled"]
        assert (disabled["color"], disabled["backgroundColor"]) != (normal["color"], normal["backgroundColor"])
        _check_contrast(page, "#project-results-search", theme, issues, placeholder=True, border=True)
        _check_contrast(page, "#project-detail-meta", theme, issues)
        page.evaluate("window.scrollTo(0, 0)")
        _shot(page, f"{theme}-project")

        page.click("#tab-btn-pro")
        _check_contrast(page, ".mode-card-title", theme, issues)
        _check_contrast(page, "#process-step-template > summary", theme, issues)
        if not page.locator(".source-profile-panel > summary").first.is_visible():
            page.check("#pro-lsv-advanced-mode")
        _check_contrast(page, ".source-profile-panel > summary", theme, issues)
        _check_contrast(page, ".module-advanced-control label", theme, issues)
        for selector in ("#pro-area", "#pro-offset", "#proc-folder"):
            _check_contrast(page, selector, theme, issues, border=True)
            _check_contrast(page, selector, theme, issues, placeholder=True)
        _check_contrast(page, "#proc-source-summary", theme, issues)
        for selector in ("#proc-preflight-btn", "#proc-run"):
            _check_contrast(page, selector, theme, issues)
            _settle_hover(page.locator(selector))
            _check_contrast(page, selector, theme + " hover", issues)
        page.evaluate("window.scrollTo(0, 0)")
        _shot(page, f"{theme}-professional")

        # Wait for the real task API refresh before measuring reused dialog DOM.
        page.evaluate("() => ElectrochemTaskCenter.open()")
        page.wait_for_selector('[data-task-id="appearance-succeeded"]')
        for status in ("succeeded", "failed", "running", "interrupted"):
            _check_contrast(page, f'[data-task-id="appearance-{status}"] .task-status', theme, issues)
        _check_contrast(page, "#task-prev", theme, issues)
        assert page.locator("#task-prev").is_disabled()
        page.click("#task-center-close")
        page.click("#appearance-open")
        _check_contrast(page, "#appearance-hint", theme, issues)
        for selector in ("#appearance-font-size", "#appearance-density", "#appearance-chart-background"):
            _check_contrast(page, selector, theme, issues, border=True)
        _shot(page, f"{theme}-appearance")
        page.click("#appearance-close")
    if len({tuple(values) for values in header_heights.values()}) != 1:
        issues.append({"state": "header-action-heights-change-between-themes", "heights": header_heights})
    _report("desktop-contrast", issues)


def _selection(page):
    return page.evaluate("""() => ({ project: selectedProjectId, record: selectedProjectHistoryKey,
      selectedKeys: ElectrochemProjectWorkbench.selectedKeys(), payload: collectProcessPayload() })""")


def _check_fit(page, selector, context, issues):
    node = page.locator(selector)
    assert node.is_visible(), (context, selector)
    node.scroll_into_view_if_needed()
    geometry = node.evaluate("""node => ({left: node.getBoundingClientRect().left, right: node.getBoundingClientRect().right,
      width: node.clientWidth, scrollWidth: node.scrollWidth, viewport: innerWidth,
      textInput: node.tagName === 'INPUT' && ['text', 'search'].includes(node.type)})""")
    # A long path may scroll inside its native text input; its outer box must fit.
    inner_overflow = not geometry["textInput"] and geometry["scrollWidth"] > geometry["width"] + 1
    if geometry["left"] < -1 or geometry["right"] > geometry["viewport"] + 1 or inner_overflow:
        issues.append({"context": context, "selector": selector, **geometry})


def test_large_text_density_keep_processing_selection_and_mobile_controls(recovery_browser):
    page, payload = _prepare(recovery_browser)
    page.click("#tab-btn-pro")
    page.fill("#pro-area", "2.75")
    page.fill("#pro-offset", "0.197")
    page.evaluate("""payload => {
      document.getElementById('proc-folder').value = payload.folder_path;
      processSourceItems = payload.input_files.map(item => ({...item, enabled:true}));
      document.querySelectorAll('.proc-type-check').forEach(node => {node.checked = node.value === 'CV'; node.dispatchEvent(new Event('change', {bubbles:true}));});
      renderProcessSourceList();
    }""", payload)
    initial = _selection(page)
    assert initial["project"] == payload["project_id"] and initial["record"] and len(initial["selectedKeys"]) == 1
    issues = []
    page.set_viewport_size({"width": 600, "height": 900})
    for theme in THEMES:
        for density in ("comfortable", "compact"):
            context = f"{theme} extra-large {density}"
            page.click("#appearance-open")
            page.locator(f'[name="appearance-theme"][value="{theme}"]').check()
            page.select_option("#appearance-font-size", "extra-large")
            page.select_option("#appearance-density", density)
            for selector in ("#appearance-dialog", "#appearance-font-size", "#appearance-density", "#appearance-chart-background", "#appearance-close", "#appearance-reset"):
                _check_fit(page, selector, context, issues)
            _shot(page, f"{theme}-{density}-600-appearance")
            page.click("#appearance-close")
            assert _selection(page) == initial, context
            page.click("#tab-btn-project")
            for selector in (*HEADER_ACTIONS, "#project-results-search", "#project-history-detail-panel"):
                _check_fit(page, selector, context, issues)
            heights = [page.locator(selector).evaluate("node => node.getBoundingClientRect().height") for selector in HEADER_ACTIONS]
            if max(heights) - min(heights) > 1:
                issues.append({"context": context, "state": "mobile-header-actions-not-equal", "heights": heights})
            if not page.evaluate("document.documentElement.scrollWidth <= innerWidth"):
                issues.append({"context": context, "state": "project-document-overflow", "width": page.evaluate("document.documentElement.scrollWidth")})
            page.click("#tab-btn-pro")
            for selector in ("#proc-folder", "#pro-area", "#pro-offset", "#proc-preflight-btn", "#proc-run"):
                _check_fit(page, selector, context, issues)
            if not page.evaluate("document.documentElement.scrollWidth <= innerWidth"):
                issues.append({"context": context, "state": "professional-document-overflow", "width": page.evaluate("document.documentElement.scrollWidth")})
            assert _selection(page) == initial, context
    _report("mobile-layout", issues)
