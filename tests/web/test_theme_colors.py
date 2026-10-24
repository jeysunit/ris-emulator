"""画面の色の値（app/web/static/app.css の変数）：グレーは中立で、文字と地の対比は WCAG 2.2 の AA（4.5:1）以上."""

from __future__ import annotations

import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "app.css"
_DECLARATION = re.compile(r"(--[a-z-]+):\s*(#[0-9a-fA-F]{6});")

# 文字の色と、その文字が乗る地（変数の名前は 3 製品の画面の決まりのトークンと同じ）。状態のバッジ
# （白い字と --color-success・--color-label）は、状態の色を前の値のまま にする方針のため対象外
# （暗い地の --color-success は白い字で AA に届かない）
_TEXT_PAIRS = [
    ("--color-foreground", "--color-background"),
    ("--color-foreground", "--color-surface"),
    ("--color-foreground", "--color-muted"),
    ("--color-foreground", "--color-selected"),
    ("--color-label", "--color-background"),
    ("--color-label", "--color-surface"),
    ("--color-label", "--color-muted"),
    ("--color-link", "--color-background"),
    ("--color-link", "--color-surface"),
    ("--color-link", "--color-muted"),
    ("--color-primary-foreground", "--color-primary"),
    ("--color-danger", "--color-surface"),
]
_NEUTRAL = (
    "--color-background", "--color-surface", "--color-foreground", "--color-label",
    "--color-border", "--color-muted",
)  # fmt: skip


def _themes() -> dict[str, dict[str, str]]:
    css = CSS.read_text(encoding="utf-8")
    dark_start = css.index("@media (prefers-color-scheme: dark)")
    light = dict(_DECLARATION.findall(css[:dark_start]))
    dark = {**light, **dict(_DECLARATION.findall(css[dark_start : css.index("* {", dark_start)]))}
    return {"light": light, "dark": dark}


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_text_contrast_is_at_least_aa() -> None:
    for theme, tokens in _themes().items():
        for foreground, background in _TEXT_PAIRS:
            ratio = _contrast(tokens[foreground], tokens[background])
            assert ratio >= 4.5, (theme, foreground, background, round(ratio, 2))


def test_greys_are_neutral() -> None:
    for theme, tokens in _themes().items():
        for name in _NEUTRAL:
            value = tokens[name].lower()
            assert value[1:3] == value[3:5] == value[5:7], (theme, name, value)


def test_accent_values() -> None:
    themes = _themes()
    assert themes["light"]["--color-primary"].lower() == "#4b4fbf"
    assert themes["dark"]["--color-link"].lower() == "#a5a8ff"


def test_mr_mark_is_purple_and_there_is_no_dark_chrome_token() -> None:
    """MR の印は赤紫（青い CT と見分ける）。暗い外枠は使わないので、そのトークンも持たない."""
    themes = _themes()
    assert themes["light"]["--color-mod-mr"].lower() == "#9333ea"
    assert themes["dark"]["--color-mod-mr"].lower() == "#c084fc"
    for tokens in themes.values():
        assert "--color-chrome" not in tokens
    assert "--color-chrome" not in CSS.read_text(encoding="utf-8")
