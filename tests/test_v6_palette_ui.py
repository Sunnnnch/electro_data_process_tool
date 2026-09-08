"""Independent visual styles and palettes through UI, migration and native bridge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from test_v6_appearance_ui import DEFAULTS, LEGACY_DEFAULTS
from test_v6_appearance_ui import appearance_browser as appearance_browser
from test_v6_assistant_appearance_ui import _contrast
from test_v6_desktop_ui import desktop_browser as desktop_browser
from test_v6_replicate_groups import seed
from test_v6_replicate_groups_ui import browser_project as browser_project
from test_v6_replicate_groups_ui import open_selection

STYLES = ("modern", "paper", "soft", "pixel")
PRESETS = ("lab", "ocean", "dark", "cream", "slate", "amber", "mist", "handheld", "violet")
COLORS = {
    "background": "#E4E9F0", "surface": "#F8FAFD", "primary": "#355B8C",
    "text": "#25374B", "titlebar": "#B9CADF",
}
STORAGE_KEY = "electrochem_v6_appearance"


def _prefs(page):
    return page.evaluate("ElectrochemTheme.getPreferences()")


def _palette(page):
    return page.evaluate("ElectrochemTheme.getPalette()")


def _set_palette(page, value):
    return page.evaluate("value => ElectrochemTheme.setPalette(value)", value)


def _style(page, name):
    page.evaluate("style => ElectrochemTheme.setStyle(style)", name)


def _token(page, name):
    return page.evaluate("name => getComputedStyle(document.body).getPropertyValue(name).trim().toUpperCase()", name)


def _rendered(page):
    page.locator("#proc-run").evaluate("async node => { await Promise.all(node.getAnimations().map(animation => animation.finished)); }")
    return page.evaluate("""() => {
      const style = selector => getComputedStyle(document.querySelector(selector));
      return {
        page: style('body').backgroundColor, panel: style('.card').backgroundColor,
        action: style('#proc-run').backgroundColor,
        scrollbar: style('html').scrollbarColor,
        heroRadius: style('.hero').borderTopLeftRadius,
        buttonRadius: style('#proc-run').borderTopLeftRadius,
        cardRadius: style('.card').borderTopLeftRadius,
        cardBorderWidth: style('.card').borderTopWidth,
      };
    }""")


def test_palette_keeps_legacy_preferences_and_default_first_paint(appearance_browser):
    old = {**LEGACY_DEFAULTS, "theme": "pixel", "fontSize": "large", "density": "compact", "grid": True}
    expected = {**DEFAULTS, "style": "pixel", "fontSize": "large", "density": "compact", "grid": True}
    page = appearance_browser(storage={STORAGE_KEY: json.dumps(old)})
    assert _prefs(page) == expected
    assert _palette(page)["id"] == "cream"
    assert page.evaluate("window.__appearanceFrames") == ["pixel"] * 3
    page.click("#appearance-open")
    assert page.locator('input[name="appearance-palette"][value="cream"]').is_checked()
    assert "像素复古" in page.locator('[data-appearance-style="pixel"]').inner_text()
    assert page.locator('[data-appearance-style]').count() == 4
    assert page.locator('input[name="appearance-style"][value="classic"]').count() == 0
    assert page.locator('input[name="appearance-palette"][value="default"]').count() == 0
    page.reload(wait_until="networkidle")
    assert _prefs(page) == expected


def test_all_style_preset_combinations_keep_geometry_and_remove_previous_colors(appearance_browser):
    page = appearance_browser()
    page.evaluate("ElectrochemTheme.update({fontSize:'large',density:'compact',grid:true})")
    for style in STYLES:
        _style(page, style)
        baseline = _rendered(page)
        initial_inline = page.evaluate("[document.body,document.documentElement].map(node => node.style.getPropertyValue('--primary'))")
        for preset in PRESETS:
            chosen = _set_palette(page, preset)
            assert chosen["id"] == preset
            assert page.locator("body").get_attribute("data-style") == style
            # Original Ocean keeps its two-stop backdrop; its first color is
            # the palette's page background rather than a flattened replacement.
            assert chosen["colors"]["background"] in _token(page, "--body-bg")
            assert _token(page, "--panel-solid") == chosen["colors"]["surface"]
            assert _token(page, "--primary") == chosen["colors"]["primary"]
            rendered = _rendered(page)
            assert rendered["heroRadius"] == baseline["heroRadius"], (style, preset)
            assert rendered["buttonRadius"] == baseline["buttonRadius"], (style, preset)
            assert rendered["cardRadius"] == baseline["cardRadius"], (style, preset)
            assert rendered["cardBorderWidth"] == baseline["cardBorderWidth"], (style, preset)
            assert _prefs(page)["fontSize"] == "large"
            assert _prefs(page)["density"] == "compact"
            assert _prefs(page)["grid"] is True
        page.evaluate("ElectrochemTheme.resetPalette()")
        assert _rendered(page) == baseline, style
        assert page.evaluate("[document.body,document.documentElement].map(node => node.style.getPropertyValue('--primary'))") == initial_inline


def test_palette_remembers_each_style_and_custom_hex_after_reload(appearance_browser):
    page = appearance_browser()
    page.fill("#pro-area", "2.75")
    expected = {}
    for style, palette in zip(STYLES, ("mist", "cream", "violet", {"id": "custom", "colors": COLORS}), strict=True):
        _style(page, style)
        expected[style] = _set_palette(page, palette)
        assert page.locator("#pro-area").input_value() == "2.75"
    page.reload(wait_until="networkidle")
    assert _prefs(page)["paletteByStyle"] == {"modern": {"id": "mist"}, "paper": {"id": "cream"}, "soft": {"id": "violet"}, "pixel": expected["pixel"]}
    page.click("#appearance-open")
    for style in reversed(STYLES):
        page.locator(f'input[name="appearance-style"][value="{style}"]').check()
        assert _palette(page) == expected[style]
        assert page.locator(f'input[name="appearance-palette"][value="{expected[style]["id"]}"]').is_checked()
        assert _token(page, "--body-bg") == expected[style]["colors"]["background"]
    page.locator('input[name="appearance-style"][value="pixel"]').check()
    for key, value in COLORS.items():
        assert page.locator(f"#appearance-color-{key}").input_value().upper() == value
        assert page.locator(f"#appearance-color-{key}-hex").input_value().upper() == value


@pytest.mark.parametrize("style", ["paper", "soft", "pixel"])
def test_system_palette_follows_light_dark_without_changing_style(appearance_browser, style):
    page = appearance_browser(color_scheme="light")
    _set_palette(page, "amber")
    _style(page, style)
    _set_palette(page, "system")
    assert _palette(page)["id"] == "lab"
    assert page.locator("body").get_attribute("data-style") == style
    radius = _rendered(page)["buttonRadius"]
    page.emulate_media(color_scheme="dark")
    page.wait_for_function("() => document.body.dataset.theme === 'dark'")
    assert _palette(page)["id"] == "dark"
    assert page.locator("body").get_attribute("data-style") == style
    assert _rendered(page)["buttonRadius"] == radius
    assert page.evaluate("ElectrochemTheme.getPaletteSelection()") == {"id": "system"}
    page.reload(wait_until="networkidle")
    assert _prefs(page)["style"] == style
    assert _palette(page)["id"] == "dark"
    page.evaluate("ElectrochemTheme.resetPalette()")
    assert _palette(page)["id"] == DEFAULTS["paletteByStyle"][style]["id"]
    assert _prefs(page)["paletteByStyle"] == {**DEFAULTS["paletteByStyle"], "modern": {"id": "amber"}}
    page.emulate_media(color_scheme="light")
    assert _palette(page)["id"] == DEFAULTS["paletteByStyle"][style]["id"]
    _style(page, "modern")
    assert _palette(page)["id"] == "amber"


def test_corrupt_custom_colors_fall_back_without_losing_other_preferences(appearance_browser):
    old = {**DEFAULTS, "fontSize": "large", "density": "compact", "chartBackground": "paper"}
    for invalid in ("#12345g", "var(--primary)", "#fff;background:url(https://invalid.example)"):
        stored = {**old, "paletteByStyle": {
            "modern": {"id": "custom", "colors": {**COLORS, "text": invalid}},
            "pixel": {"id": "amber"},
            "unknown": {"id": "cream"},
        }}
        page = appearance_browser(storage={STORAGE_KEY: json.dumps(stored)})
        assert _palette(page)["id"] == "lab"
        prefs = _prefs(page)
        assert {key: prefs[key] for key in old if key != "paletteByStyle"} == {key: old[key] for key in old if key != "paletteByStyle"}
        assert prefs["paletteByStyle"] == {**DEFAULTS["paletteByStyle"], "pixel": {"id": "amber"}}
        assert invalid not in page.evaluate("document.body.style.cssText")
        _style(page, "pixel")
        assert _palette(page)["id"] == "amber"
        page.context.close()


def test_custom_palette_warns_on_low_contrast_and_has_scoped_resets(appearance_browser):
    page = appearance_browser(width=600)
    _set_palette(page, "slate")
    _style(page, "pixel")
    page.fill("#pro-area", "2.5")
    page.click("#appearance-open")
    page.select_option("#appearance-font-size", "large")
    page.locator('input[name="appearance-palette"][value="custom"]').check()
    surface = page.locator("#appearance-color-surface").input_value()
    page.fill("#appearance-color-text-hex", surface)
    page.locator("#appearance-color-text-hex").press("Tab")
    page.locator("#appearance-palette-contrast").wait_for(state="visible")
    assert _palette(page)["colors"]["text"] == surface.upper()
    page.click("#appearance-color-auto-text")
    page.locator("#appearance-palette-contrast").wait_for(state="hidden")
    colors = page.evaluate("""() => {
      const node = document.querySelector('.appearance-content');
      const css = getComputedStyle(node), dialog = getComputedStyle(document.querySelector('#appearance-dialog'));
      return [css.color, dialog.backgroundColor];
    }""")
    assert _contrast(*colors) >= 4.5
    invalid = page.locator("#appearance-color-primary-hex")
    previous = _palette(page)["colors"]["primary"]
    invalid.fill("#12345G")
    invalid.press("Tab")
    assert _palette(page)["colors"]["primary"] == previous
    size = page.locator("#appearance-dialog").evaluate("node => [node.clientWidth,node.scrollWidth]")
    assert size[1] <= size[0] + 1
    page.click("#appearance-palette-reset")
    assert _palette(page)["id"] == "cream"
    assert _prefs(page)["style"] == "pixel"
    assert _prefs(page)["fontSize"] == "large"
    assert _prefs(page)["paletteByStyle"] == {**DEFAULTS["paletteByStyle"], "modern": {"id": "slate"}}
    page.click("#appearance-reset")
    assert _prefs(page) == DEFAULTS
    page.keyboard.press("Escape")
    assert page.locator("#pro-area").input_value() == "2.5"


def test_palette_updates_real_plot_preview_but_keeps_paper_and_export_colors(browser_project):
    page, base_url, project_id = browser_project
    seed(project_id, "palette-one", 1)
    seed(project_id, "palette-two", 3)
    open_selection(page, base_url)
    page.fill("#replicate-name", "Palette preview")
    with page.expect_response(lambda response: response.url.endswith("/replicate-preview")) as reviewed:
        page.click("#replicate-review")
    assert reviewed.value.ok
    with page.expect_response(lambda response: response.url.endswith("/replicate-groups") and response.request.method == "POST") as saved:
        page.click("#replicate-save")
    assert saved.value.ok
    page.locator("#replicate-csv").wait_for(state="visible")
    page.wait_for_selector("#replicate-chart svg")
    series = '#replicate-chart [data-chart-series]'
    before = page.locator(series).evaluate_all("nodes => nodes.map(node => [node.tagName,node.getAttribute('fill'),node.getAttribute('cx'),node.getAttribute('cy'),node.getAttribute('points')])")
    _set_palette(page, "amber")
    rect = page.locator('#replicate-chart [data-chart-part="background"]')
    assert rect.evaluate("node => getComputedStyle(node).fill") == "rgb(42, 36, 28)"
    page.evaluate("ElectrochemTheme.update({chartBackground:'paper'})")
    _set_palette(page, "violet")
    assert rect.evaluate("node => getComputedStyle(node).fill") == "rgb(255, 255, 255)"
    after = page.locator(series).evaluate_all("nodes => nodes.map(node => [node.tagName,node.getAttribute('fill'),node.getAttribute('cx'),node.getAttribute('cy'),node.getAttribute('points')])")
    assert after == before
    with page.expect_download() as downloaded:
        page.click("#replicate-svg")
    exported = Path(downloaded.value.path()).read_text(encoding="utf-8")
    assert 'fill="white"' in exported or 'fill="#ffffff"' in exported.lower()
    assert "#CDB2EE" not in exported.upper()


def test_custom_palette_syncs_native_caption_and_restores_on_new_port(desktop_browser):
    open_page, native, _calls, _source, _project, _conversation = desktop_browser
    page = open_page()
    colors = {**COLORS, "titlebar": "#243449"}
    chosen = _set_palette(page, {"id": "custom", "colors": colors})
    page.evaluate("ElectrochemDesktop.syncWindowAppearance()")
    assert native["window_appearance"]["caption_color"] == "#243449"
    assert native["window_appearance"]["dark"] is True
    page.evaluate("ElectrochemDesktop.persist()")
    restored = open_page(new_port=True)
    assert _palette(restored) == chosen
    restored.evaluate("ElectrochemDesktop.syncWindowAppearance()")
    assert native["window_appearance"]["caption_color"] == "#243449"
    _set_palette(restored, {"id": "custom", "colors": COLORS})
    restored.evaluate("ElectrochemDesktop.syncWindowAppearance()")
    assert native["window_appearance"]["caption_color"] == COLORS["titlebar"]
    assert native["window_appearance"]["dark"] is False
    restored.evaluate("ElectrochemTheme.resetPalette()")
    restored.evaluate("ElectrochemDesktop.syncWindowAppearance()")
    assert native["window_appearance"]["caption_color"] == "#C6D6E3"


def test_legacy_custom_palettes_are_preserved_and_can_be_restored(appearance_browser):
    customized = {name: {"id": "custom", "colors": {**COLORS, "primary": color}}
                  for name, color in (("lab", "#3A6482"), ("ocean", "#655388"), ("dark", "#7C483A"), ("pixel", "#506340"))}
    legacy = {**LEGACY_DEFAULTS, "theme": "dark", "fontSize": "large", "paletteByTheme": customized}
    page = appearance_browser(storage={STORAGE_KEY: json.dumps(legacy)})
    assert _prefs(page)["style"] == "modern"
    assert _prefs(page)["paletteByStyle"] == {**DEFAULTS["paletteByStyle"], "modern": customized["dark"], "pixel": customized["pixel"]}
    assert _prefs(page)["fontSize"] == "large"
    recovered = page.evaluate("ElectrochemTheme.getRecoveredPalettes()")
    assert {item["id"] for item in recovered} == {"legacy-lab", "legacy-ocean"}
    assert {item["colors"]["primary"] for item in recovered} == {"#3A6482", "#655388"}
    page.click("#appearance-open")
    page.locator("#appearance-recovered-palettes > summary").click()
    page.locator('[data-recovered-palette="legacy-lab"]').click()
    assert _palette(page) == customized["lab"]
    assert page.evaluate("ElectrochemTheme.getRecoveredPalettes()") == recovered
    page.reload(wait_until="networkidle")
    assert _palette(page) == customized["lab"]
    assert page.evaluate("ElectrochemTheme.getRecoveredPalettes()") == recovered
    _style(page, "pixel")
    assert _palette(page) == customized["pixel"]
    page.evaluate("ElectrochemTheme.reset()")
    assert _prefs(page) == DEFAULTS
    assert page.evaluate("ElectrochemTheme.getRecoveredPalettes()") == []
    system_page = appearance_browser(storage={STORAGE_KEY: json.dumps({**legacy, "theme": "system"})}, color_scheme="dark")
    assert system_page.evaluate("ElectrochemTheme.getPaletteSelection()") == {"id": "system"}
    assert _palette(system_page)["id"] == "dark"
    assert {item["id"] for item in system_page.evaluate("ElectrochemTheme.getRecoveredPalettes()")} == {"legacy-lab", "legacy-ocean", "legacy-dark"}
    _style(system_page, "pixel")
    assert _palette(system_page) == customized["pixel"]


def test_two_style_v2_settings_gain_new_defaults_without_losing_saved_choices(appearance_browser):
    recovered = [{"id": "legacy-ocean", "labelKey": "appearance_palette_recovered_ocean", "colors": {**COLORS, "primary": "#705E88"}}]
    old = {**DEFAULTS, "style": "pixel", "fontSize": "extra-large", "density": "compact", "grid": True,
           "chartBackground": "paper", "paletteByStyle": {"modern": {"id": "custom", "colors": COLORS}, "pixel": {"id": "system"}},
           "recoveredPalettes": recovered}
    expected = {**old, "paletteByStyle": {**DEFAULTS["paletteByStyle"], **old["paletteByStyle"]}}
    page = appearance_browser(storage={STORAGE_KEY: json.dumps(old)}, color_scheme="dark")
    assert _prefs(page) == expected
    assert page.evaluate("window.__appearanceFrames") == ["dark"] * 3
    assert page.evaluate("ElectrochemTheme.getRecoveredPalettes()") == recovered
    page.click("#appearance-open")
    for style in ("paper", "soft"):
        page.locator(f'input[name="appearance-style"][value="{style}"]').check()
        assert page.locator(f'[data-appearance-style="{style}"]').evaluate("node => node.classList.contains('selected')")
        assert page.locator(f'input[name="appearance-palette"][value="{DEFAULTS["paletteByStyle"][style]["id"]}"]').is_checked()
    page.locator('input[name="appearance-palette"][value="amber"]').check()
    page.reload(wait_until="networkidle")
    expected["style"] = "soft"
    expected["paletteByStyle"]["soft"] = {"id": "amber"}
    assert _prefs(page) == expected
    assert _palette(page)["id"] == "amber"
    _style(page, "modern")
    assert _palette(page) == old["paletteByStyle"]["modern"]
    _style(page, "pixel")
    assert page.evaluate("ElectrochemTheme.getPaletteSelection()") == {"id": "system"}


@pytest.mark.parametrize("active_style", ["classic", "modern"])
def test_removed_classic_preserves_existing_pixel_and_restores_custom_colors_from_ui(appearance_browser, active_style):
    classic = {"id": "custom", "colors": {**COLORS, "primary": "#68527F"}}
    pixel = {"id": "custom", "colors": {**COLORS, "primary": "#506340"}}
    old = {**DEFAULTS, "style": active_style, "fontSize": "large", "density": "compact",
           "paletteByStyle": {"modern": {"id": "ocean"}, "classic": classic,
                              "paper": {"id": "cream"}, "soft": {"id": "violet"}, "pixel": pixel}}
    page = appearance_browser(storage={STORAGE_KEY: json.dumps(old)})
    expected_style = "pixel" if active_style == "classic" else "modern"
    prefs = _prefs(page)
    assert prefs["style"] == expected_style
    assert page.locator("body").get_attribute("data-style") == expected_style
    assert prefs["paletteByStyle"] == {key: value for key, value in old["paletteByStyle"].items() if key != "classic"}
    assert prefs["fontSize"] == "large" and prefs["density"] == "compact"
    recovered = page.evaluate("ElectrochemTheme.getRecoveredPalettes()")
    saved_classic = next(item for item in recovered if item["id"] == "legacy-classic")
    assert saved_classic["colors"] == classic["colors"]
    assert saved_classic["selection"] == classic
    page.reload(wait_until="networkidle")
    assert _prefs(page) == prefs
    page.fill("#pro-area", "2.75")
    page.click("#appearance-open")
    assert page.locator('input[name="appearance-style"]').evaluate_all("nodes => nodes.map(node => node.value)") == list(STYLES)
    page.locator('input[name="appearance-style"][value="pixel"]').check()
    assert _palette(page) == pixel
    page.locator("#appearance-recovered-palettes > summary").click()
    page.locator('[data-recovered-palette="legacy-classic"]').click()
    assert _palette(page) == classic
    assert page.locator("#appearance-color-primary-hex").input_value().upper() == classic["colors"]["primary"]
    page.keyboard.press("Escape")
    assert page.locator("#pro-area").input_value() == "2.75"
    page.reload(wait_until="networkidle")
    assert _prefs(page)["style"] == "pixel" and _palette(page) == classic
    assert page.evaluate("ElectrochemTheme.getRecoveredPalettes()") == recovered


@pytest.mark.parametrize("classic_selection,pixel_selection", [
    ({"id": "dark"}, None),
    ({"id": "system"}, {"id": "invalid-palette"}),
], ids=["preset-with-missing-pixel", "system-with-invalid-pixel"])
def test_removed_classic_palette_migrates_when_pixel_missing_and_restores_selection_semantics(appearance_browser, classic_selection, pixel_selection):
    palettes = {"modern": {"id": "ocean"}, "classic": classic_selection}
    if pixel_selection is not None:
        palettes["pixel"] = pixel_selection
    old = {**DEFAULTS, "style": "classic", "grid": True, "chartBackground": "paper", "paletteByStyle": palettes}
    page = appearance_browser(storage={STORAGE_KEY: json.dumps(old)}, color_scheme="dark")
    assert _prefs(page)["style"] == "pixel"
    assert _prefs(page)["paletteByStyle"]["pixel"] == classic_selection
    assert _palette(page)["id"] == "dark"
    assert _prefs(page)["grid"] is True and _prefs(page)["chartBackground"] == "paper"
    recovered = page.evaluate("ElectrochemTheme.getRecoveredPalettes()")
    assert next(item for item in recovered if item["id"] == "legacy-classic")["selection"] == classic_selection
    page.reload(wait_until="networkidle")
    assert _prefs(page)["paletteByStyle"]["pixel"] == classic_selection
    page.click("#appearance-open")
    page.locator('input[name="appearance-palette"][value="amber"]').check()
    page.locator("#appearance-recovered-palettes > summary").click()
    page.locator('[data-recovered-palette="legacy-classic"]').click()
    assert page.evaluate("ElectrochemTheme.getPaletteSelection()") == classic_selection
    assert page.locator(f'input[name="appearance-palette"][value="{classic_selection["id"]}"]').is_checked()
    page.emulate_media(color_scheme="light")
    expected = "lab" if classic_selection["id"] == "system" else "dark"
    page.wait_for_function("expected => ElectrochemTheme.getPalette().id === expected", arg=expected)
    assert page.locator("body").get_attribute("data-style") == "pixel"
