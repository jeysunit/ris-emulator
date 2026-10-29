"""画面の色の値（app/web/static/ui-kit/tokens.css の変数）：グレーは中立で、文字と地の対比は WCAG 2.2 の AA（4.5:1）以上."""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "app" / "web" / "static"
CSS = STATIC / "ui-kit" / "tokens.css"
APP_CSS = STATIC / "app.css"
_DECLARATION = re.compile(r"(--[a-z-]+):\s*(#[0-9a-fA-F]{6});")

# 文字の色と、その文字が乗る地（変数の名前は 3 製品の画面の決まりのトークンと同じ）。状態の札
# （.st）の字は --color-foreground（取消だけ --color-label）で、状態の色は枠と印だけに使う
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
    # 暗い地は 2 か所（端末の設定に従うときと、html[data-theme=dark] で選んだとき）にあり、同じ値
    css = CSS.read_text(encoding="utf-8")
    dark_start = css.index("@media (prefers-color-scheme: dark)")
    chosen_start = css.index(":root[data-theme=dark]")
    light = dict(_DECLARATION.findall(css[:dark_start]))
    dark = {**light, **dict(_DECLARATION.findall(css[dark_start:chosen_start]))}
    chosen = {**light, **dict(_DECLARATION.findall(css[chosen_start:]))}
    assert chosen == dark
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


# 文字でない部品（状態の札の枠と印、入力欄の枠）の色と地。対比は WCAG 2.2 の 1.4.11 の 3:1 以上
_NON_TEXT = (
    "--color-border-input", "--color-success", "--color-warning", "--color-danger",
)  # fmt: skip


def test_non_text_contrast_is_at_least_3_to_1_on_both_themes() -> None:
    """状態の札の枠・印と入力欄の枠は、明るい地でも暗い地でも、地（background・surface）に対し 3:1 以上."""
    for theme, tokens in _themes().items():
        for name in _NON_TEXT:
            for ground in ("--color-background", "--color-surface"):
                ratio = _contrast(tokens[name], tokens[ground])
                assert ratio >= 3.0, (theme, name, ground, round(ratio, 2))


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
    assert "--color-chrome" not in APP_CSS.read_text(encoding="utf-8")


def test_app_css_holds_no_tokens_and_reads_after_the_ui_kit() -> None:
    """色の値は ui-kit の tokens.css だけが持つ。app.css は製品の差分だけで、ui-kit の後に読む."""
    assert not _DECLARATION.findall(APP_CSS.read_text(encoding="utf-8"))
    base = (STATIC.parent / "templates" / "base.html").read_text(encoding="utf-8")
    links = re.findall(r'<link rel="stylesheet" href="([^"]+)">', base)
    assert links == ["/static/ui-kit/tokens.css", "/static/ui-kit/components.css", "/static/app.css"]
    assert (STATIC / "ui-kit" / "VERSION").read_text(encoding="utf-8").strip() == "1.2.3"
