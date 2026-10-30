"""上の帯の接続の状態・「接続確認」・接続先の画面（docs/spec/03_web_cli.md 3.1）.

確かめられる相手は 2 つ：自分の MWL の待ち受け（C-ECHO）と、HL7 の送信先（MLLP の接続を開けるか。
何も送らない）。直近の結果はこの画面のプロセスの中だけに持つ。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from app.hl7.mllp import check_connection
from app.mwl.server import MwlServer
from app.services.config import Hl7Config

logger = logging.getLogger(__name__)

# 手で押した結果の読み上げの 3 つ目の型。要求が届かなかった・断られたとき（app.js が入れる）
CHECK_UNREADABLE = "接続を確かめられませんでした。"
# 接続確認で接続を待つ時間（秒）。画面の操作なので、送信の時間切れ（設定）より短く打ち切る
HL7_CHECK_TIMEOUT_SECONDS = 3.0

# 失敗の理由ごとの、次にすること（接続先の画面の知らせ）。接続先は設定ファイルで決めるので、
# 直す場所を設定ファイルの項目名で書く
NEXT_STEPS = {
    "応答がありません": "相手の電源とネットワーク、ホスト名・ポート番号（hl7.host・hl7.port）を確かめてください。",
    "接続を断られました": "相手が HL7 を待ち受けているか、ポート番号（hl7.port）が合っているかを確かめてください。",
    "ホスト名を引けません": "ホスト名（hl7.host）の綴りと名前解決の設定を確かめてください。",
}


@dataclass(frozen=True)
class Probe:
    """接続確認の直近の結果（MWL の待ち受けは C-ECHO、HL7 の送信先は MLLP の接続）."""

    ok: bool
    at: str
    reason: str = ""


@dataclass(frozen=True)
class ConnView:
    """上の帯のボタンと popover、接続先の画面に出す札."""

    overall_kind: str
    overall_label: str
    mwl_kind: str
    mwl_label: str
    mwl_time: str
    hl7_kind: str
    hl7_label: str
    hl7_time: str
    hl7_reason: str


def check_summary(results: list[bool]) -> str:
    """手で押した「接続確認」の結果を読み上げる 1 文（部品集の 3 つの型の、確かめられた場合の 2 つ）.

    N は確かめた件数、M は失敗の件数。
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


def run_hl7_check(config: Hl7Config) -> Probe:
    """HL7 の送信先の MLLP の接続を開けるかを確かめ、結果を時刻つきで返す（何も送らない）."""
    timeout = min(config.timeout_seconds, HL7_CHECK_TIMEOUT_SECONDS)
    result = check_connection(config.host, config.port, timeout)
    if not result.ok:
        logger.info("HL7 の送信先 %s:%s に接続できません：%s", config.host, config.port, result.detail)
    return Probe(ok=result.ok, at=now_label(), reason=result.reason)


def hl7_notice(config: Hl7Config, probe: Probe) -> tuple[str, str]:
    """接続先の画面の、押した直後の知らせ（種類・文）。何が起きたか・なぜか・次にすること."""
    target = f"{config.receiving_application}（{config.host}:{config.port}）"
    if probe.ok:
        return "ok", f"{target}に接続できました。"
    steps = NEXT_STEPS.get(probe.reason, "")
    return "err", f"{target}に接続できません。{probe.reason}。{steps}"


def conn_view(mwl: MwlServer, probe: Probe | None, hl7_probe: Probe | None = None) -> ConnView:
    """全体の札と、MWL・HL7 の行の札.

    待ち受けが止まっているか、どちらかの直近の確かめが失敗なら「一部が接続不可」。まだ確かめていない
    HL7 の送信先は札「未確認」で、全体の札を下げない（MWL の待ち受けも、確かめる前は動いているかで決める）。
    """
    ok = mwl.running and (probe is None or probe.ok) and (hl7_probe is None or hl7_probe.ok)
    if not mwl.running:
        mwl_kind, mwl_label = "ng", "停止"
    elif probe is not None and not probe.ok:
        mwl_kind, mwl_label = "ng", "失敗"
    else:
        mwl_kind, mwl_label = "listen", "待ち受け中"
    if hl7_probe is None:
        hl7_kind, hl7_label = "plan", "未確認"
    elif hl7_probe.ok:
        hl7_kind, hl7_label = "ok", "成功"
    else:
        hl7_kind, hl7_label = "ng", "失敗"
    return ConnView(
        overall_kind="ok" if ok else "ng",
        overall_label="接続中" if ok else "一部が接続不可",
        mwl_kind=mwl_kind,
        mwl_label=mwl_label,
        mwl_time=probe.at if probe is not None else "",
        hl7_kind=hl7_kind,
        hl7_label=hl7_label,
        hl7_time=hl7_probe.at if hl7_probe is not None else "",
        hl7_reason=hl7_probe.reason if hl7_probe is not None and not hl7_probe.ok else "",
    )
