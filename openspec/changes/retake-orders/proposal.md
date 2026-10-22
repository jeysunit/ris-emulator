# Proposal

## Why

撮影をやり直すとき、施設によって検査の扱いが違う。

- (A) IHE の Scheduled Workflow の形：同じ予約・同じ Study Instance UID の中で、シリーズを
  追加して撮り直す。RIS の予約は増えない
- (B) 施設のローカルルールの形：撮り直しは別の検査で、受付番号から Study Instance UID まで
  変わる。RIS に撮り直しの予約が要る

今の RIS は (A) の形しか試験できない。(B) の施設のモダリティと PACS を試験するには、
元の予約を写して新しい番号を発番した「撮り直しの予約」を作れる必要がある。どちらの形を
使うかを設定で選べるようにする。モダリティの側も同じ考え方の設定を持つ前提で、設定の
値の名前をそろえる。

## What Changes

- 設定に `orders.retake_policy` を足す。`same_study`（(A)、既定）と `new_order`（(B)）から選ぶ
- `new_order` のとき、予約の詳細の画面と CLI の `retake <受付番号>` で、撮り直しの予約を作る。
  元の予約の患者・モダリティ・装置・検査・依頼の内容・文字コードを写し、受付番号・
  Requested Procedure ID・Scheduled Procedure Step ID・Study Instance UID を新しく発番する。
  予定日時は作った時点（指定もできる）、状態は予定
- 撮り直しの予約に元の受付番号を残し、予約の詳細に、元の予約と撮り直しの予約を互いに表示する
- 撮り直しを作れるのは、元の予約が実施中・完了・中止のとき。元の予約が実施中なら中止にし、
  完了・中止ならそのままにする（推奨。design.md に3つの案）
- `same_study` のときは、撮り直しの予約を作る機能を出さない（CLI はエラー）。追加のシリーズの
  MPPS を受けても予約を増やさない。最初の MPPS が中止になった予約に、同じ予約の新しい
  MPPS（IN PROGRESS）が来たら、予約を実施中に戻す

## Capabilities

### New Capabilities

- `retake`: 撮り直しの扱いの設定と、撮り直しの予約の作り方・元の予約との関係

### Modified Capabilities

- `order-status`: `same_study` のときだけ、MPPS による「中止 → 実施中」を許す
- `mpps-scp`: 終わりの状態の予約に MPPS が来たときの例外（上と同じ）

## Impact

- コード：`app/services/config.py`（`retake_policy`）、`app/core/models.py`（`Order.retake_of`）、
  `app/services/order_service.py`・`store.py`（撮り直しの予約の作成と元の予約の状態の変更を
  1つのトランザクションで行う）、`app/cli/main.py`（`retake`）、`app/web/app.py`・
  `order_detail.html`、`app/mwl/server.py`（`same_study` の例外）
- テスト：撮り直しの作成、番号の発番、元の予約の状態、2つの設定での MPPS の試験を足す
- ドキュメント：`docs/spec/01_orders.md`・`03_web_cli.md`・MPPS の spec、`docs/usage.md`、ADR
- 前提：`order-status-transitions` と `mpps-scp` を先に archive する。`station-registry` を
  先に archive していれば装置の名前も写す
- 既定は `same_study` なので、設定を変えない利用者の動作は `mpps-scp` の後と同じ
