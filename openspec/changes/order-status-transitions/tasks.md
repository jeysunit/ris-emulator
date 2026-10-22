# Tasks

## 1. 遷移の表とストア

- [ ] 1.1 `app/core/models.py` に `ALLOWED_TRANSITIONS` と `can_transition` を足し、16 通りの組み合わせ（同じ状態を含む）を `tests/core/` の試験で確かめる
- [ ] 1.2 `app/core/exceptions.py` に `InvalidTransitionError`（`ValidationError` の子）を足し、`OrderStore.set_status` が `BEGIN IMMEDIATE` の中で今の状態を確かめ、許さない遷移では `ROLLBACK` して投げ、同じ状態では更新日時を変えずに返すことを `tests/services/test_order_service.py` の試験で確かめる

## 2. CLI と画面

- [ ] 2.1 CLI の `status` で、完了の予約を `scheduled` にすると終了コード 2 と今の状態を書いたエラーになり、完了に `completed` を指定すると終了コード 0 になることを `tests/cli/test_cli.py` で確かめる
- [ ] 2.2 `_order_row.html`・`order_detail.html` の選択肢を、今の状態と変更できる状態だけにし、完了・取消では状態の名前だけを出すことを `tests/web/test_web.py` で確かめる
- [ ] 2.3 `POST /orders/{受付番号}/status` が許さない遷移で 400 を返し、状態と更新日時が変わらないことを `tests/web/test_web.py` で確かめる

## 3. ドキュメントと全体の確かめ

- [ ] 3.1 `docs/spec/01_orders.md` の 5 章に遷移の表を書き、`docs/spec/03_web_cli.md` の CLI の表と終了コードを合わせ、markdownlint が合格することを確かめる
- [ ] 3.2 `python -m pytest -q` がすべて合格することを確かめる

## Workflow follow-up

- PR のレビューの後に、この change を archive する（`mpps-scp` より先に archive する）
