"""アプリの版（docs/spec/03_web_cli.md 3 章。版の付け方は docs/development.md の 6 章）.

版の正は git のタグ（vX.Y.Z）。イメージを作るときに scripts/app-version.sh が git から作り、
環境変数 APP_VERSION で渡す。X.Y.Z（タグの上）、X.Y.Z+N.gHASH（タグより後）、0.0.0+unknown（不明）の形だけを受ける。
手元の開発の起動（APP_VERSION が無く、scripts/app-version.sh がある作業ツリー）では git から直に作る。
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

APP_VERSION_ENV = "APP_VERSION"
UNKNOWN_VERSION = "0.0.0+unknown"
_VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(\+[0-9A-Za-z.]+)?")
_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "app-version.sh"


@lru_cache(maxsize=1)
def _version_from_git() -> str:
    if not _SCRIPT.is_file():
        return ""
    try:
        done = subprocess.run(
            ["sh", str(_SCRIPT)], cwd=_SCRIPT.parent, capture_output=True, text=True, timeout=5, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip()


def app_version(env: Mapping[str, str] | None = None) -> str:
    """画面と CLI に出す版。分からなければ 0.0.0+unknown."""
    raw = (os.environ if env is None else env).get(APP_VERSION_ENV, "").strip()
    if not raw and env is None:
        raw = _version_from_git()
    return raw if _VERSION_PATTERN.fullmatch(raw) else UNKNOWN_VERSION
