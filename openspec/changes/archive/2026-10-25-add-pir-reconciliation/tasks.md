# Tasks

## 1. 未照合の撮影の読み取り

- [x] 1.1 `app/core/reconciliation.py` に MPPS の記録から仮の患者・Study Instance UID・モダリティ・装置・開始日時を読む関数を書き、読めない値・照合できない撮影を `tests/core/test_reconciliation.py` で確かめる
- [x] 1.2 送る HL7 の決め方（A40・A08・ORM だけ）を試験で確かめる

## 2. 保存と照合

- [x] 2.1 `reconciliations` の表と、未照合の MPPS の一覧、照合の確定（予約・結び付け・記録を 1 つのトランザクション）、送信の記録の更新を `app/services/store.py` に書く
- [x] 2.2 `app/services/reconciliation.py` に照合と送信（順に送り、受理されなかった 1 通で止める。再送信は同じ本文）を書き、`tests/services/test_reconciliation.py` で A40・A08・ORM だけ・拒否・通信の失敗・再送信・照合済み・入力の誤り・巻き戻しを確かめる

## 3. 画面と CLI

- [x] 3.1 「未照合」の一覧、照合の画面、予約の詳細の「HL7 送信」の表と再送信を足し、`tests/web/test_reconciliation.py` で確かめる
- [x] 3.2 `reconcile list`・`run`・`resend` を足し、`tests/cli/test_cli_reconcile.py` で終了コードを確かめる

## 4. ドキュメント

- [x] 4.1 `docs/spec/07_reconciliation.md`・ADR-0011・`docs/spec/03_web_cli.md`・`05_mpps_scp.md`・`06_hl7_pir.md`・`docs/usage.md`・`docs/architecture.md`・`docs/project_charter.md`・`docs/README.md` を直し、markdownlint が合格することを確かめる
- [x] 4.2 `python -m pytest -q` がすべて合格し、CI が緑であることを確かめる

## Workflow follow-up

- PR のレビューの後に、この change を archive する
