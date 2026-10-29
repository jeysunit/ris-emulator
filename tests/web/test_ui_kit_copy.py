"""ui-kit の写し（app/web/static/ui-kit/）が指紋（SHA256SUMS）と合い、製品の側で直されていないことの試験."""

from __future__ import annotations

import hashlib
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
