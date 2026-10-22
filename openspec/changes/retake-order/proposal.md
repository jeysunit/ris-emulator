# Proposal

## Why

撮影をやり直すとき、施設によって検査の扱いが違う。

- `append`：IHE の Append Case。同じ予約・同じ Study Instance UID の中で、2つ目以降の MPPS と
  シリーズを追加して撮り直す（IHE RAD TF-2 4.6.4.1.2.3.3。例に「画質が悪い画像の撮り直し」がある）。
  RIS の予約は増えない
- `new_order`：施設のローカルルール。撮り直しは別の検査で、受付番号から Study Instance UID まで
  変わる。RIS に撮り直しの予約が要る

今の RIS は `append` の形しか試験できない。`new_order` の施設のモダリティと PACS を試験するには、
元の予約を写して新しい番号を発番した「撮り直しの予約」を作れる必要がある。どちらの形を使うかを
設定で選べるようにする。モダリティの側も同じ名前・同じ値の設定を持つ前提にする。

## What Changes

- 設定に `orders.retake_mode` を足す。値は `append`（既定）と `new_order`
- `append` のときは、RIS は撮り直しで何もしない。同じ予約に2つ目以降の MPPS が来ても、
  `mpps-scp` の規則のとおりに記録し、予約が終わりの状態なら状態は変えない。撮り直しの予約を
  作る機能は出さない（CLI はエラー）
- `new_order` のとき、予約の詳細の画面と CLI の `retake <受付番号>` で、撮り直しの予約を作る。
  元の予約の患者・モダリティ・装置・検査・依頼の内容・文字コードを写し、受付番号・
  Requested Procedure ID・Scheduled Procedure Step ID・Study Instance UID を新しく発番する。
  予定日時は作った時点（指定もできる）、状態は予定
- 撮り直しの予約に元の受付番号（`retake_of`）を残し、予約の詳細に、元の予約と撮り直しの予約を
  互いに表示する
- 撮り直しを作れるのは、元の予約が実施中・完了・中止のとき。元の予約が実施中なら中止にし、
  完了・中止ならそのままにする（推奨。design.md に3つの案）

## Capabilities

### New Capabilities

- `retake`: 撮り直しの扱いの設定と、撮り直しの予約の作り方・元の予約との関係

### Modified Capabilities

（なし。`order-status` と `mpps-scp` の要件は変えない。元の予約を中止にするのは、`order-status` の
遷移の表の「実施中 → 中止」の範囲）

## Impact

- コード：`app/services/config.py`（`retake_mode`）、`app/core/models.py`（`Order.retake_of`）、
  `app/services/order_service.py`・`store.py`（撮り直しの予約の作成と元の予約の状態の変更を
  1つのトランザクションで行う）、`app/cli/main.py`（`retake`）、`app/web/app.py`・`order_detail.html`
- テスト：撮り直しの作成、番号の発番、元の予約の状態、2つの設定での動作の試験を足す
- ドキュメント：`docs/spec/01_orders.md`・`03_web_cli.md`、`docs/usage.md`、ADR
- 前提：`order-status-transitions` と `mpps-scp` を先に archive する（中止の状態と MPPS の記録を使う）
- 既定は `append` なので、設定を変えない利用者の動作は `mpps-scp` の後と同じ
