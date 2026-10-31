# Tasks

## 1. 照合の後の撮影

- [x] 1.1 `app/mwl/mpps.py` と `app/services/store.py` で、受付番号が空の項目を Study Instance UID と患者ID で照合で作った予約に結び付け、`tests/services/test_reconciliation.py` で仮・正式・別の患者ID、ふつうの予約、受付番号のある項目、完了の予約を確かめる

## 2. 取消・中止の ORM

- [x] 2.1 `build_orm_o01` の ORC-1・ORC-5 を引数で決め、`tests/hl7/test_messages.py` で NW・CA・DC・XO と不正な値を確かめる
- [x] 2.2 `ReconciliationService.set_status` と `OrderStore.set_status` で、照合で作った予約の取消・中止に CA・DC の通を同じトランザクションで足して送り、送る順・同じ状態・ふつうの予約・MPPS の中止・巻き戻しを試験で確かめる
- [x] 2.3 画面の状態の変更と CLI の `status` を新しい処理に替え、`pir send --order-control` を足して、画面と CLI の試験で確かめる

## 3. ドキュメント

- [x] 3.1 ADR-0012 を足し、`docs/spec/03_web_cli.md`・`05_mpps_scp.md`・`06_hl7_pir.md`・`07_reconciliation.md`・`docs/usage.md`・`docs/project_charter.md` を直し、markdownlint が合格することを確かめる
- [x] 3.2 `python -m pytest -q` がすべて合格し、CI が緑であることを確かめる

## Workflow follow-up

- PR のレビューの後に、この change を archive する
