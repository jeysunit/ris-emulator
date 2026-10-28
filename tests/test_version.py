"""版を git のタグから作る仕組み（app/version.py と scripts/app-version.sh）の試験."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.version import UNKNOWN_VERSION, app_version

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "app-version.sh"


def test_app_version_accepts_only_version_shapes() -> None:
    assert app_version({"APP_VERSION": "0.2.0"}) == "0.2.0"
    assert app_version({"APP_VERSION": " 0.2.0+37.g60970f9 "}) == "0.2.0+37.g60970f9"
    assert app_version({"APP_VERSION": "0.0.0+unknown"}) == UNKNOWN_VERSION


def test_app_version_is_unknown_when_not_passed_or_malformed() -> None:
    assert app_version({}) == UNKNOWN_VERSION
    for bad in ("v0.2.0", "0.2", "0.2.0+", "0.2.0 rm", "0.2.0+a;b"):
        assert app_version({"APP_VERSION": bad}) == UNKNOWN_VERSION


def test_app_version_reads_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    assert app_version() == "1.2.3"


def test_app_version_falls_back_to_git_only_in_a_work_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.version as version

    monkeypatch.delenv("APP_VERSION")
    # イメージの中にはスクリプトも .git も無いので、不明になる
    monkeypatch.setattr(version, "_SCRIPT", tmp_path / "missing" / "app-version.sh")
    version._version_from_git.cache_clear()
    assert app_version() == UNKNOWN_VERSION
    # 作業ツリーでは、スクリプトが作った値を使う
    monkeypatch.setattr(version, "_SCRIPT", SCRIPT)
    version._version_from_git.cache_clear()
    assert app_version() == subprocess.run(["sh", str(SCRIPT)], capture_output=True, text=True).stdout.strip()
    version._version_from_git.cache_clear()


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, capture_output=True, text=True, check=True,
    )  # fmt: skip
    return done.stdout.strip()


def _commit(cwd: Path, name: str) -> None:
    (cwd / name).write_text(name)
    _git(cwd, "add", name)
    _git(cwd, "commit", "-q", "-m", name)


def _run_script(cwd: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    # 作業用の一時フォルダの親より上の git を見に行かせない
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(cwd.parent))
    return subprocess.run(["sh", str(SCRIPT)], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    return repo


def test_script_on_a_tag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _commit(repo, "a")
    _git(repo, "tag", "v0.2.0")
    assert _run_script(repo, monkeypatch) == "0.2.0"


def test_script_after_a_tag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _commit(repo, "a")
    _git(repo, "tag", "v0.2.0")
    _commit(repo, "b")
    _commit(repo, "c")
    short = _git(repo, "rev-parse", "--short", "HEAD")
    assert _run_script(repo, monkeypatch) == f"0.2.0+2.g{short}"


def test_script_without_any_tag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _commit(repo, "a")
    _commit(repo, "b")
    short = _git(repo, "rev-parse", "--short", "HEAD")
    assert _run_script(repo, monkeypatch) == f"0.0.0+2.g{short}"


def test_script_without_git_information(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bare = tmp_path / "no-git"
    bare.mkdir()
    assert _run_script(bare, monkeypatch) == UNKNOWN_VERSION
