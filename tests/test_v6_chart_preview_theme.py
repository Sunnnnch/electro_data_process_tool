"""Screen appearance changes preserve scientific marks and exported artifacts."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from xml.etree import ElementTree

from electrochem_v6.core.replicate_service import save_replicates
from electrochem_v6.store.runtime import get_database
from test_v6_replicate_groups import draft, seed
from test_v6_replicate_groups_ui import browser_project, open_selection  # noqa: F401


def _contrast(first, second):
    def luminance(css):
        rgb = [float(value) / 255 for value in re.findall(r"[\d.]+", css)[:3]]
        assert len(rgb) == 3, css
        linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in rgb]
        return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))
    levels = sorted((luminance(first), luminance(second)))
    return (levels[1] + .05) / (levels[0] + .05)


def _appearance(page, theme, background="theme"):
    page.evaluate("""({ theme, background }) => {
      ElectrochemTheme.save(theme);
      ElectrochemTheme.update({ chartBackground: background });
    }""", {"theme": theme, "background": background})


def _screenshot(page, name, selector):
    folder = os.environ.get("ELECTROCHEM_APPEARANCE_SCREENSHOTS")
    if not folder:
        return
    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    chart = page.locator(selector)
    assert chart.is_visible()
    chart.scroll_into_view_if_needed()
    chart.screenshot(path=str(target / f"{name}-chart.png"), animations="disabled")
    page.screenshot(path=str(target / f"{name}-page.png"), full_page=False, animations="disabled")


def _svg_state(page):
    return page.locator("#replicate-chart svg").evaluate("""svg => ({
      background: getComputedStyle(svg.querySelector('[data-chart-part="background"]')).fill,
      text: getComputedStyle(svg.querySelector('[data-chart-part="text"]')).fill,
      axis: getComputedStyle(svg.querySelector('[data-chart-part="axis"]')).stroke,
      outline: getComputedStyle(svg.querySelector('[data-chart-series="measurement"]')).stroke,
      identity: Array.from(svg.querySelectorAll('[data-chart-series]')).map(node => ({
        series: node.dataset.chartSeries, tag: node.tagName, fill: node.getAttribute('fill'),
        stroke: node.dataset.chartSeries === 'sample-sd' ? node.getAttribute('stroke') : null,
        cx: node.getAttribute('cx'), cy: node.getAttribute('cy'), points: node.getAttribute('points'), d: node.getAttribute('d')
      }))
    })""")


def test_replicate_preview_themes_preserve_points_and_white_exports(request):
    page, base_url, project_id = request.getfixturevalue("browser_project")
    keys = [seed(project_id, "first", 0), seed(project_id, "second", 2)]
    group = save_replicates(project_id, draft(keys))
    exports = {kind: page.request.get(f"{base_url}/api/v1/replicate-groups/{group['group_id']}/export?format={kind}&metric=tafel_slope").body()
               for kind in ("csv", "svg")}
    open_selection(page, base_url)
    page.wait_for_selector("#replicate-chart svg")
    original = _svg_state(page)["identity"]
    page.evaluate("window.originalChartNode = document.querySelector('#replicate-chart svg')")
    backgrounds = {}
    for theme in ("lab", "dark", "ocean", "pixel"):
        _appearance(page, theme)
        state = _svg_state(page)
        backgrounds[theme] = state["background"]
        assert state["identity"] == original
        assert page.evaluate("window.originalChartNode === document.querySelector('#replicate-chart svg')")
        assert _contrast(state["outline"], state["background"]) >= 3, (theme, state)
        assert _contrast(state["axis"], state["background"]) >= 3, (theme, state)
        assert _contrast(state["text"], state["background"]) >= 4.5, (theme, state)
        if theme in {"lab", "dark"}:
            _screenshot(page, f"{theme}-vector-theme", "#replicate-chart")
        _appearance(page, theme, "paper")
        paper = _svg_state(page)
        assert paper["background"] == "rgb(255, 255, 255)"
        assert paper["identity"] == original
        if theme in {"lab", "dark"}:
            _screenshot(page, f"{theme}-vector-paper", "#replicate-chart")
        for kind, before in exports.items():
            after = page.request.get(f"{base_url}/api/v1/replicate-groups/{group['group_id']}/export?format={kind}&metric=tafel_slope").body()
            assert after == before
    assert backgrounds["dark"] != backgrounds["lab"]
    svg = ElementTree.fromstring(exports["svg"])
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    paper = svg.find("svg:rect", namespace)
    assert paper is not None and paper.get("fill") == "white"
    measurements = svg.findall(".//svg:circle[@data-chart-series='measurement']", namespace)
    means = svg.findall(".//svg:polygon[@data-chart-series='mean']", namespace)
    assert len(measurements) == 2 and all(node.get("fill") == "#236db4" for node in measurements)
    assert len(means) == 1 and means[0].get("fill") == "#087856"
    assert means[0].get("data-chart-marker") == "diamond"


def test_project_compare_png_uses_paper_without_changing_original_file(request, tmp_path):
    from electrochem_v6.core.project_compare import build_project_lsv_compare_plot

    page, base_url, project_id = request.getfixturevalue("browser_project")
    for name, values in (("curve-one", [1, 5, 10]), ("curve-two", [2, 6, 12])):
        key = seed(project_id, name)
        record = get_database().get_history_record(key)
        assert record is not None
        record["data"] = {"potential_original": [-.3, -.2, -.1], "potential_compensated": [-.29, -.19, -.09], "current": values}
        get_database().add_history_record(record)
    result = build_project_lsv_compare_plot(project_id=project_id, selected_samples=["curve-one", "curve-two"], output_dir=str(tmp_path / "plots"))
    assert result["status"] == "success"
    plot = result["plot"]
    image_file = Path(plot["plot_path"])
    original_hash = hashlib.sha256(image_file.read_bytes()).hexdigest()
    page.goto(base_url + "/ui", wait_until="networkidle")
    page.click("#tab-btn-project")
    page.wait_for_selector(".project-record-check")
    page.click("#project-tab-compare")
    page.click("#project-lsv-comparison > summary")
    page.wait_for_load_state("networkidle")
    page.evaluate("""plot => ElectrochemProjectComparePage.renderPlot({
      byId: id => document.getElementById(id), escapeHtml: ElectrochemUiCore.escapeHtml,
      model: ElectrochemProjectCompareModel, state: { selectedSamples: ['curve-one', 'curve-two'], chartType: 'curve', plotData: plot },
      t: key => I18N.en[key] || key, bindFileActions: () => {}
    })""", plot)
    image = page.locator("#project-compare-plot .chart-paper img")
    image.evaluate("image => image.decode()")
    assert "Original chart" in page.locator("#project-compare-plot .chart-preview-note").text_content()
    image.evaluate("image => { window.originalScientificImage = image; }")
    for theme in ("lab", "dark", "ocean", "pixel"):
        for background in ("theme", "paper"):
            _appearance(page, theme, background)
            assert image.get_attribute("src") == plot["image_data_url"]
            assert image.evaluate("image => image === window.originalScientificImage")
            assert image.evaluate("image => getComputedStyle(image).filter") == "none"
            assert image.evaluate("image => getComputedStyle(image).mixBlendMode") == "normal"
            assert image.evaluate("""image => {
              for (let node = image; node; node = node.parentElement) {
                if (getComputedStyle(node).filter !== 'none' || getComputedStyle(node).mixBlendMode !== 'normal') return false;
              }
              return true;
            }""")
            assert image.evaluate("image => getComputedStyle(image.parentElement).backgroundColor") == "rgb(255, 255, 255)"
            assert image.evaluate("image => image.naturalWidth > 0")
            assert hashlib.sha256(image_file.read_bytes()).hexdigest() == original_hash
            if theme == "dark" and background == "theme":
                _screenshot(page, "dark-original-png-paper", "#project-compare-plot")
