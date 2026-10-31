# Proposal

## Why

照合（`add-pir-reconciliation`）の後も、モダリティが仮の患者のまま同じ Study で撮る
ことがある（IHE PIR の Case 6）。この撮影の MPPS は受付番号が空なので予約に結び付かず、
未照合の一覧に残る。もう一度照合すると、同じ Study Instance UID の予約が 2 つできる。

また、照合で作った予約は PACS に ORM の NW で知らせているが、その予約を取消・中止しても
PACS には知らせていない。IHE は取消・中止・変更を Procedure Update [RAD-13] の
ORM（ORC-1 が CA・DC・XO）で知らせるとしている。PACS の RAD-13 の受け取りを試す相手が
要る。

## What Changes

- MPPS の N-CREATE で、受付番号が空の項目の Study Instance UID が照合で作った予約と同じで、
  MPPS の Patient ID がその照合の仮の患者ID か正式な患者ID と同じなら、その予約に結び付ける
- 照合で作った予約を画面・CLI で取消・中止にしたら、ORM^O01（CA・DC）を照合の送信の
  末尾に足して送る。状態の変更と通の追加は 1 つのトランザクション。送る順・記録・
  再送信は照合の送信と同じ
- MPPS の N-SET による中止と、照合で作っていない予約では送らない
- `build_orm_o01` の ORC-1 を引数にし、CLI の `pir send` に `--order-control`
  （NW・CA・DC・XO）を足す
- CLI の `status` は、ORM を送ったときに HL7 の結果で終了コードを返す
- ADR-0012 を足し、spec の 03・05・06・07、usage、憲章を直す

## Capabilities

### New Capabilities

（なし）

### Modified Capabilities

- `pir-reconciliation`: 照合の後の撮影の結び付け、照合で作った予約の取消・中止の知らせ
- `mpps-scp`: 受付番号が空の項目を、照合で作った予約に結び付ける
- `hl7-sender`: ORM^O01 の ORC-1 に CA・DC・XO を入れられる

## Impact

- コード：`app/core/hl7.py`・`app/core/reconciliation.py`・`app/mwl/mpps.py`・
  `app/services/store.py`・`app/services/reconciliation.py`・`app/web/app.py`・
  `app/cli/main.py`
- データベース：表は変えない（照合の記録の送信に、新しい種類 `orm_ca`・`orm_dc` の通が
  足される。前の記録はそのまま読める）
- テスト：`tests/services/test_reconciliation.py`・`tests/hl7/test_messages.py`・
  `tests/cli/test_cli_reconcile.py`・`tests/cli/test_cli_pir.py`・
  `tests/web/test_reconciliation.py`
- 依存：追加しない
- 範囲外：XO の自動の送信（予約の中身を後から変える操作が無い）、ふつうの予約の
  HL7 の知らせ、照合の取り消し
