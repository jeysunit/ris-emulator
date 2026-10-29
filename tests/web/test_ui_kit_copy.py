"""ui-kit の写し（app/web/static/ui-kit/）が指紋（SHA256SUMS）と合い、製品の側で直されていないことの試験."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

KIT = Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "ui-kit"
FILES = ["tokens.css", "components.css", "icons.svg", "VERSION"]


def _sums() -> dict[str, str]:
    sums = {}
    for line in (KIT / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        sums[name.strip()] = digest
    return sums


def test_copy_matches_the_fingerprints() -> None:
    sums = _sums()
    assert sorted(sums) == sorted(FILES)
    for name in FILES:
        assert hashlib.sha256((KIT / name).read_bytes()).hexdigest() == sums[name], name


def test_product_css_and_templates_do_not_keep_the_old_parts() -> None:
    """ui-kit の .notice・.empty に替えた古い部品（.error・.empty-box）を、定義も使いも残さない."""
    static = KIT.parent
    css = (static / "app.css").read_text(encoding="utf-8")
    assert not re.search(r"\.(error|empty-box)\b", css)
    for template in (static.parent / "templates").glob("*.html"):
        text = template.read_text(encoding="utf-8")
        assert not re.search(r'class="[^"]*\b(error|empty-box)\b', text), template.name


def test_product_css_does_not_restyle_the_patient_banner() -> None:
    """患者バナーの幅・切り方は ui-kit の .fb が持つ。製品の app.css で上書きしない."""
    css = (KIT.parent / "app.css").read_text(encoding="utf-8")
    assert not re.search(r"\.fb\b", css)
