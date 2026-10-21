"""ADR の最終更新日の確かめ（scripts/check_doc_dates.py、docs/development.md 3 章）の試験."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts.check_doc_dates import check, is_dated_document, main

ADR_A = "docs/decisions/0001-a.md"


def _git(repo: Path, *args: str, day: str = "2026-10-22", check: bool = True) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": f"{day}T12:00:00+09:00",
        "GIT_COMMITTER_DATE": f"{day}T12:00:00+09:00",
    }
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo, env=env, check=check, capture_output=True,
    )


def _doc(updated: str) -> str:
    return f"# ADR-0001: 題\n\n- 状態：採用\n- 作成日：2026-10-21\n- 最終更新日：{updated}\n\n本文\n"


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _git(tmp_path, "init", "-q")
    (tmp_path / "docs" / "decisions").mkdir(parents=True)
    (tmp_path / ADR_A).write_text(_doc("2026-10-21"), encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base", day="2026-10-21")
    _git(tmp_path, "tag", "base")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _commit(repo: Path, path: str, text: str, day: str = "2026-10-22") -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change", day=day)


def test_updated_date_on_commit_day_passes(repo: Path) -> None:
    _commit(repo, ADR_A, _doc("2026-10-22"))
    assert check("base..HEAD") == []


def test_stale_updated_date_fails(repo: Path) -> None:
    _commit(repo, ADR_A, _doc("2026-10-21") + "追記\n")
    problems = check("base..HEAD")
    assert len(problems) == 1
    assert ADR_A in problems[0]
    assert main(["base..HEAD"]) == 1


def test_later_commit_fixes_earlier_omission(repo: Path) -> None:
    _commit(repo, ADR_A, _doc("2026-10-21") + "追記\n", day="2026-10-22")
    _commit(repo, ADR_A, _doc("2026-10-23") + "追記\n", day="2026-10-23")
    assert check("base..HEAD") == []


def test_only_last_change_in_range_counts(repo: Path) -> None:
    _commit(repo, ADR_A, _doc("2026-10-22"), day="2026-10-22")
    _commit(repo, ADR_A, _doc("2026-10-22") + "追記\n", day="2026-10-23")
    problems = check("base..HEAD")
    assert len(problems) == 1
    assert "2026-10-23" in problems[0]


def test_deleted_document_is_skipped(repo: Path) -> None:
    _git(repo, "rm", "-q", ADR_A)
    _git(repo, "commit", "-q", "-m", "remove")
    assert check("base..HEAD") == []


def test_japanese_path_is_checked(repo: Path) -> None:
    _commit(repo, "docs/decisions/0002-日本語.md", "# 題\n\n本文\n")
    problems = check("base..HEAD")
    assert len(problems) == 1
    assert "docs/decisions/0002-日本語.md" in problems[0]


def test_renamed_document_is_checked(repo: Path) -> None:
    _git(repo, "mv", ADR_A, "docs/decisions/0001-b.md")
    _git(repo, "commit", "-q", "-m", "rename")
    problems = check("base..HEAD")
    assert len(problems) == 1
    assert "docs/decisions/0001-b.md" in problems[0]


def test_invalid_date_is_reported_as_document_problem(repo: Path) -> None:
    _commit(repo, ADR_A, _doc("2026-02-30"))
    problems = check("base..HEAD")
    assert "日付として読めない" in problems[0]
    assert main(["base..HEAD"]) == 1


def test_merge_that_drops_the_date_fails(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, ADR_A, _doc("2026-10-22") + "側\n")
    _git(repo, "checkout", "-q", "-")
    _commit(repo, ADR_A, _doc("2026-10-22") + "本線\n")
    # 衝突させるので失敗してよい。CI には git の利用者の設定が無いので _git で名前を渡す
    _git(repo, "merge", "-q", "side", check=False)
    (repo / ADR_A).write_text("# 題\n\n解消\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-edit", day="2026-10-23")
    problems = check("base..HEAD")
    assert len(problems) == 1
    assert "最終更新日" in problems[0]


def test_merge_that_fixes_the_date_passes(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, ADR_A, _doc("2026-10-21") + "側\n")
    _git(repo, "checkout", "-q", "-")
    _commit(repo, ADR_A, _doc("2026-10-21") + "本線\n")
    # 衝突させるので失敗してよい。CI には git の利用者の設定が無いので _git で名前を渡す
    _git(repo, "merge", "-q", "side", check=False)
    (repo / ADR_A).write_text(_doc("2026-10-23") + "解消\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-edit", day="2026-10-23")
    assert check("base..HEAD") == []


def test_missing_header_fails(repo: Path) -> None:
    _commit(repo, "docs/decisions/0003-x.md", "# ADR-0003: x\n\n本文\n")
    assert "最終更新日" in check("base..HEAD")[0]


def test_non_adr_documents_are_skipped(repo: Path) -> None:
    _commit(repo, "README.md", "# 題\n\n本文\n")
    _commit(repo, "docs/spec/01_x.md", "# 題\n\n本文\n")
    _commit(repo, "docs/decisions/README.md", "# 一覧\n")
    _commit(repo, "docs/decisions/template.md", "# ADR-NNNN: 題\n")
    assert check("base..HEAD") == []


def test_bad_range_returns_2(repo: Path) -> None:
    assert main(["no-such-ref..HEAD"]) == 2


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("README.md", False),
        ("docs/spec/01_orders.md", False),
        ("docs/decisions/README.md", False),
        ("docs/decisions/0003-identifiers-fit-dicom-and-hl7.md", True),
        ("docs/decisions/template.md", False),
        ("app/README.md", False),
    ],
)
def test_is_dated_document(path: str, expected: bool) -> None:
    assert is_dated_document(path) is expected
