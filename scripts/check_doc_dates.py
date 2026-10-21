#!/usr/bin/env python3
"""変更した ADR の「最終更新日」が、その commit の日より古くないかを確かめる.

使い方: python scripts/check_doc_dates.py origin/main..HEAD

範囲の中で足した・直した ADR（docs/decisions/NNNN-*.md。雛形と README は除く）ごとに、
範囲の中でその ADR を最後に変えた commit の中身を読む。
冒頭の「- 最終更新日：YYYY-MM-DD」が無いか、その commit の日（committer の日付）より
古ければ失敗する。途中の commit で付け忘れても、後の commit で直してあれば通る。
「最後に変えた commit」は git log の履歴の単純化に従う。merge でどちらの親とも違う
中身にしたときは、その merge を見る。
終了コード：0=問題なし、1=古い・無い文書がある、2=引数や git の誤り。
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import date

HEADER_LINES = 10
UPDATED = re.compile(r"^- 最終更新日：(\d{4}-\d{2}-\d{2})\s*$")
ADR = re.compile(r"^docs/decisions/\d{4}-[^/]+\.md$")


class GitError(Exception):
    """git が失敗した."""


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def is_dated_document(path: str) -> bool:
    """最終更新日の行を持つべき文書（ADR）か."""
    return ADR.match(path) is not None


def last_updated(text: str) -> str | None:
    """冒頭の「最終更新日」の値（YYYY-MM-DD の文字列）。無ければ None."""
    for line in text.splitlines()[:HEADER_LINES]:
        match = UPDATED.match(line)
        if match:
            return match.group(1)
    return None


def changed_paths(revision_range: str) -> set[str]:
    """範囲の commit が足した・直した・名前を変えたパス。merge は親ごとの差分を見る."""
    output = git("log", "-m", "--format=", "--name-only", "-z", "--diff-filter=AMR", revision_range)
    return {path.strip("\n") for path in output.split("\0") if path.strip("\n")}


def last_change(revision_range: str, path: str) -> tuple[str, date] | None:
    """範囲の中でそのパスを最後に変えた commit と、その commit の日."""
    output = git(
        "--literal-pathspecs", "log", "-1", "--topo-order", "--format=%H %cs",
        revision_range, "--", path,
    ).strip()
    if not output:
        return None
    commit, day = output.split(" ")
    return commit, date.fromisoformat(day)


def exists_at(commit: str, path: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}:{path}"], capture_output=True, check=False,
    )
    return result.returncode == 0


def check(revision_range: str) -> list[str]:
    problems = []
    for path in sorted(changed_paths(revision_range)):
        if not is_dated_document(path):
            continue
        found = last_change(revision_range, path)
        if found is None:
            continue
        commit, commit_day = found
        short = commit[:7]
        if not exists_at(commit, path):
            continue  # 範囲の中で最後に消した
        value = last_updated(git("show", f"{commit}:{path}"))
        if value is None:
            problems.append(f"{short} {path}: 冒頭に「- 最終更新日：YYYY-MM-DD」が無い")
            continue
        try:
            updated = date.fromisoformat(value)
        except ValueError:
            problems.append(f"{short} {path}: 最終更新日 {value} は日付として読めない")
            continue
        if updated < commit_day:
            problems.append(f"{short} {path}: 最終更新日 {updated} が commit の日 {commit_day} より古い")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        problems = check(argv[0])
    except GitError as error:
        print(error, file=sys.stderr)
        return 2
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
