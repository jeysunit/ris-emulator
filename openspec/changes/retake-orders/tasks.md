# Tasks

## 1. 前提と設定

- [ ] 1.1 `order-status-transitions` と `mpps-scp` が archive 済みで、`openspec/specs/order-status/spec.md` と `openspec/specs/mpps-scp/spec.md` があることを確かめる
- [ ] 1.2 IHE RAD TF の Scheduled Workflow で、撮り直し・追加の撮影を同じ Scheduled Procedure Step の新しい MPPS とシリーズで扱う節を原文で確かめ、節の番号を design.md の Context に書く
- [ ] 1.3 `app/services/config.py` に `orders.retake_policy`（`same_study`・`new_order`、既定 `same_study`）を足し、既定値と知らない値のエラーを `tests/services/` の試験で確かめる

## 2. 撮り直しの予約の作成

- [ ] 2.1 `Order` に `retake_of` を足し、`OrderService.create_retake` で元の予約を写して番号を新しく発番することを、spec の「番号がすべて変わる」のシナリオで `tests/services/test_order_service.py` で確かめる
- [ ] 2.2 元の予約が実施中なら中止に、完了・中止ならそのままにし、予定・取消からは作らず、`same_study` では作らないことを試験で確かめる
- [ ] 2.3 元の予約の状態の確認・撮り直しの予約の保存・元の予約の状態の変更を1つのトランザクションで行い、途中で失敗したら何も残らず連番も使わないことを試験で確かめる

## 3. CLI と画面

- [ ] 3.1 CLI の `retake <受付番号> [--date] [--start]` を足し、`new_order` での作成と、`same_study`・予定の予約での終了コード 2 を `tests/cli/test_cli.py` で確かめる
- [ ] 3.2 予約の詳細に、`new_order` のときだけ撮り直しのボタンを出し、「撮り直しの元」と「撮り直し」のリンクを出すことを `tests/web/test_web.py` で確かめる
- [ ] 3.3 撮り直しの予約が、モダリティの AE タイトルと今日の日付の C-FIND で新しい Study Instance UID で返ることを `tests/mwl/test_server.py` で確かめる

## 4. MPPS

- [ ] 4.1 `same_study` で、中止の予約に新しい MPPS の N-CREATE（IN PROGRESS）が来たら実施中に戻り、N-SET（COMPLETED）で完了になり、`new_order` では中止のままであることを `tests/mwl/` の試験で確かめる
- [ ] 4.2 `same_study` で、完了の予約に追加の MPPS が来ても予約が完了のままで、予約の数が増えないことを試験で確かめる

## 5. ドキュメントと全体の確かめ

- [ ] 5.1 `docs/spec/01_orders.md`（撮り直しの章）・`03_web_cli.md`（CLI と設定の表）・MPPS の spec・`docs/usage.md` を直し、ADR「撮り直しの扱いを設定で選ぶ」を足し、markdownlint と `python scripts/check_doc_dates.py origin/main..HEAD` が合格することを確かめる
- [ ] 5.2 `python -m pytest -q` がすべて合格することを確かめる

## Workflow follow-up

- PR のレビューの後に、この change を archive する（`order-status-transitions`・`mpps-scp` の後）
