from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("src", "tests", "docs")
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".js", ".html", ".css", ".txt", ".csv"}
SKIP_PARTS = {"__pycache__", ".pytest_cache"}
SKIP_NAMES = {"purify.min.js"}

# High-confidence UTF-8-as-GBK mojibake glyphs seen during earlier cleanup.
MOJIBAKE_ESCAPES = (
    "\\u93b6",
    "\\u7487",
    "\\u93c1",
    "\\u9422",
    "\\u9359",
    "\\u935a",
    "\\u701b",
    "\\u6f36",
    "\\u93c2",
    "\\u9239",
    "\\u922b",
    "\\u951b",
    "\\u7d1d",
    "\\u71c2",
    "\\u7d1a",
    "\\u6d5c",
    "\\u8e47",
    "\\u714e",
    "\\u568f",
    "\\u9418",
    "\\u864f",
)
MOJIBAKE_CHARS = {item.encode("ascii").decode("unicode_escape") for item in MOJIBAKE_ESCAPES}

# Keep legacy header compatibility for result tables produced by old builds:
# an old mojibake squared-unit glyph is accepted as cm2 in metric parsing,
# but new user-facing strings should not use it.
ALLOWED_LEGACY_CHARS = {
    Path("src/electrochem_v6/core/processing_metric_registry.py"): {
        "\\u864f".encode("ascii").decode("unicode_escape"),
    }
}


def _should_scan(path: Path) -> bool:
    rel_parts = set(path.relative_to(ROOT).parts)
    return (
        path.is_file()
        and path.suffix.lower() in TEXT_SUFFIXES
        and path.name not in SKIP_NAMES
        and not (rel_parts & SKIP_PARTS)
    )


def test_source_files_do_not_contain_mojibake_chinese():
    violations: list[str] = []
    for root_name in SCAN_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not _should_scan(path):
                continue
            rel_path = path.relative_to(ROOT)
            allowed = ALLOWED_LEGACY_CHARS.get(rel_path, set())
            text = path.read_text(encoding="utf-8")
            for line_number, line in enumerate(text.splitlines(), 1):
                bad = sorted({ch for ch in line if ch in MOJIBAKE_CHARS and ch not in allowed})
                if bad:
                    escaped = "".join(ch.encode("unicode_escape").decode("ascii") for ch in bad)
                    violations.append(f"{rel_path}:{line_number}: {escaped}")

    assert violations == []
