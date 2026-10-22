# Tasks

## 1. 前提と設定

- [ ] 1.1 `order-status-transitions` と `mpps-scp` が archive 済みで、`openspec/specs/order-status/spec.md` と `openspec/specs/mpps-scp/spec.md` があることを確かめる
- [ ] 1.2 `app/services/config.py` に `orders.retake_mode`（`append`・`new_order`、既定 `append`）を足し、既定値と知らない値のエラーを `tests/services/` の試験で確かめる

## 2. 撮り直しの予約の作成

- [ ] 2.1 `Order` に `retake_of` を足し、`OrderService.create_retake` で元の予約を写して番号を新しく発番することを、spec の「番号がすべて変わる」のシナリオで `tests/services/test_order_service.py` で確かめる
- [ ] 2.2 元の予約が実施中なら中止に、完了・中止ならそのままにし、予定・取消からは作らず、`append` では作らないことを試験で確かめる
- [ ] 2.3 元の予約の状態の確認・撮り直しの予約の保存・元の予約の状態の変更を1つのトランザクションで行い、途中で失敗したら何も残らず連番も使わないことを試験で確かめる

## 3. CLI と画面

- [ ] 3.1 CLI の `retake <受付番号> [--date] [--start]` を足し、`new_order` での作成と、`append`・予定の予約での終了コード 2 を `tests/cli/test_cli.py` で確かめる
- [ ] 3.2 予約の詳細に、`new_order` のときだけ撮り直しのボタンを出し、「撮り直しの元」と「撮り直し」のリンクを出すことを `tests/web/test_web.py` で確かめる
- [ ] 3.3 撮り直しの予約が、モダリティの AE タイトルと今日の日付の C-FIND で新しい Study Instance UID で返ることを `tests/mwl/test_server.py` で確かめる

## 4. append の動作

- [ ] 4.1 `append` で、完了の予約に2つ目の MPPS（N-CREATE・N-SET）が来ても 0000H を返して記録し、予約は完了のまま、予約の数も変わらないことを `tests/mwl/` の試験で確かめる

## 5. ドキュメントと全体の確かめ

- [ ] 5.1 `docs/spec/01_orders.md`（撮り直しの章）・`03_web_cli.md`（CLI と設定の表）・`docs/usage.md` を直し、ADR「撮り直しの扱いを設定で選ぶ」（出典に IHE RAD TF-2 4.6.4.1.2.3.3）を足し、markdownlint と `python scripts/check_doc_dates.py origin/main..HEAD` が合格することを確かめる
- [ ] 5.2 `python -m pytest -q` がすべて合格することを確かめる

## Workflow follow-up

- PR のレビューの後に、この change を archive する（`order-status-transitions`・`mpps-scp` の後）
