# 00. 概要

## 目的

開発・試験の環境で、RIS の役を務める。架空の患者と検査の予約を作り、
MWL（Modality Worklist、C-FIND の SCP）で返す。モダリティ
（dicom-test-generator など）がワークリストを取得し、撮影して PACS へ送る流れの、
前段を受け持つ。

## 範囲

| 段 | 内容 | 状態 |
|----|------|------|
| 1 | 予約を作る（CLI・Web 画面）、一覧と状態（手で変える）、MWL の SCP、Docker のイメージ | この版 |
| 2 | MPPS の SCP（N-CREATE・N-SET を受けて予約の状態を進める） | 設計だけ（ADR-0001） |

範囲に入れないもの：HL7 の受信、Patient Demographics・帳票、本物の患者のデータ。

## 層

```text
Web (app/web/) ─┐
CLI (app/cli/) ─┤→ Service (app/services/) → Core (app/core/)
MWL (app/mwl/) ─┘
```

- Core：予約のモデル、乱数の患者、照合、応答の組み立て。ファイル・通信・ログを使わない
- Service：設定・名簿の読み込み、予約の保存（SQLite）、予約の作成
- Web・CLI・MWL：入口。Service だけを呼ぶ

## 仕様書

| ファイル | 中身 |
|----------|------|
| [01_orders.md](01_orders.md) | 予約の項目、番号の付け方、患者の作り方、状態 |
| [02_mwl_scp.md](02_mwl_scp.md) | MWL の SCP：照合、返す属性、文字コード、状態の値 |
| [03_web_cli.md](03_web_cli.md) | Web 画面・CLI・設定・Docker |
