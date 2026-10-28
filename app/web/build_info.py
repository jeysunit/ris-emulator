"""「バージョン情報」の画面に出すビルドの commit（docs/spec/03_web_cli.md 3 章）.

イメージを作るときに環境変数 BUILD_COMMIT で渡す。16 進の 7〜40 文字だけを受け、
渡されていない・形が違うときは None（画面はその行を出さない）。
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

BUILD_COMMIT_ENV = "BUILD_COMMIT"
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{7,40}", re.IGNORECASE)


def build_commit(env: Mapping[str, str] | None = None) -> str | None:
    """ビルドの commit（小文字）。分からなければ None."""
    raw = (os.environ if env is None else env).get(BUILD_COMMIT_ENV, "").strip()
    return raw.lower() if _COMMIT_PATTERN.fullmatch(raw) else None
