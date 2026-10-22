# Proposal

## Why

予約の状態は、今は画面と CLI でどの状態からどの状態へも変更できる
（`docs/spec/01_orders.md` の 5 章）。完了・取消にした予約を予定に戻すと、MWL で
もう一度返り、同じ Study Instance UID で2回撮影できてしまう。完了・取消は終わりの
状態とし、その後は変更できないようにする（2026-10-23 の決定）。

## What Changes

- 予約の状態の遷移を表で定め、表に無い遷移は変更しない。完了（`completed`）と
  取消（`cancelled`）からは、どの状態へも変更できない
- 予定（`scheduled`）と実施中（`in_progress`）の間は、手動で行き来できる
  （実施中への誤操作を戻せるようにする）
- 今と同じ状態を指定したときは、変更せずに成功にする
- **BREAKING** CLI の `status` は、許さない遷移を入力のエラー（終了コード 2）にする。
  Web 画面は 400 を返し、状態を変えない
- Web 画面の状態の選択肢は、今の状態から変更できる状態だけを出す。完了・取消の予約は
  選択肢を出さず、状態の名前だけを表示する
- `docs/spec/01_orders.md` の 5 章の「どの状態からどの状態へも変更できる」を、遷移の表に
  置き換える

## Capabilities

### New Capabilities

- `order-status`: 予約の状態の種類、状態の遷移、MWL で返す状態

### Modified Capabilities

（なし。`openspec/specs/` にはまだ spec が無い）

## Impact

- コード：`app/core/models.py`（遷移の表）、`app/services/store.py` の `set_status`
  （遷移の検証を、読み出しと同じトランザクションで行う）、`app/services/order_service.py`、
  `app/cli/main.py` の `status`、`app/web/app.py` と `_order_row.html`・`order_detail.html`
- テスト：`tests/services/test_order_service.py`・`tests/web/test_web.py`・
  `tests/cli/test_cli.py` に遷移の試験を足す。今の試験は、予定から完了・取消・実施中への
  変更だけを使うので、そのまま通る
- ドキュメント：`docs/spec/01_orders.md` の 5 章、`docs/spec/03_web_cli.md` の CLI の表
- 利用者：完了・取消にした予約を戻す操作ができなくなる。やり直すときは新しい予約を作る
- 後に続く change：`mpps-scp` は、この change の遷移の表に「中止」を足す
