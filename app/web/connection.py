"""上の帯の接続の状態と「接続確認」（docs/spec/03_web_cli.md 3.1）.

確かめられる相手は自分の MWL の待ち受けだけ。HL7 の送信先は状態を持たない相手なので、
何も送らず、件数にも数えない。直近の結果はこの画面のプロセスの中だけに持つ。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.mwl.server import MwlServer

# 手で押した結果の読み上げの 3 つ目の型。要求が届かなかった・断られたとき（app.js が入れる）
CHECK_UNREADABLE = "接続を確かめられませんでした。"


@dataclass(frozen=True)
class Probe:
    """MWL の待ち受けに C-ECHO をかけた直近の結果."""

    ok: bool
    at: str


@dataclass(frozen=True)
class ConnView:
    """上の帯のボタンと popover に出す、MWL の待ち受けの札."""

    overall_kind: str
    overall_label: str
    mwl_kind: str
    mwl_label: str
    mwl_time: str


def check_summary(results: list[bool]) -> str:
    """手で押した「接続確認」の結果を読み上げる 1 文（部品集の 3 つの型の、確かめられた場合の 2 つ）.

    N は確かめた件数、M は失敗の件数。HL7 の送信先は状態を持たないので数えない。
    """
    total = len(results)
    failed = results.count(False)
    if failed:
        return f"{total} 件のうち {failed} 件に接続できませんでした。"
    return f"{total} 件すべてに接続できました。"


def now_label() -> str:
    # 日時は yyyy/MM/dd HH:mm（部品集の「日付と時刻」）
    return datetime.now().strftime("%Y/%m/%d %H:%M")


def run_check(mwl: MwlServer) -> Probe:
    """MWL の待ち受けに C-ECHO をかけ、結果を時刻つきで返す."""
    return Probe(ok=mwl.echo(), at=now_label())


def conn_view(mwl: MwlServer, probe: Probe | None) -> ConnView:
    """全体の札と MWL の行の札。待ち受けが止まっているか、直近の確かめが失敗なら「一部が接続不可」."""
    ok = mwl.running and (probe is None or probe.ok)
    if not mwl.running:
        mwl_kind, mwl_label = "ng", "停止"
    elif probe is not None and not probe.ok:
        mwl_kind, mwl_label = "ng", "失敗"
    else:
        mwl_kind, mwl_label = "listen", "待ち受け中"
    return ConnView(
        overall_kind="ok" if ok else "ng",
        overall_label="接続中" if ok else "一部が接続不可",
        mwl_kind=mwl_kind,
        mwl_label=mwl_label,
        mwl_time=probe.at if probe is not None else "",
    )
