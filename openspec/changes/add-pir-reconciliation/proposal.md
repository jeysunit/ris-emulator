# Proposal

## Why

予約の無い撮影（緊急の飛び込みなど）は、モダリティが仮の患者 ID と氏名で撮影するので、
RIS には MPPS だけが残る。後で正式な患者が決まると、RIS は撮影に患者と予約を結び、
PACS に HL7 v2 で知らせる必要がある（IHE の PIR）。HL7 の組み立てと送信は
`add-pir-hl7-sender` で作った。この change は、未照合の撮影を一覧し、正式な患者と予約を
結んで、その結果を HL7 で送る操作と、送信の結果の記録・再送信を作る。

## What Changes

- 予約に結び付いていない MPPS を「未照合の撮影」として一覧する（画面・CLI）
- 未照合の撮影に、正式な患者（名簿か入力）と検査名・依頼科を指定して、新しい予約を結ぶ。
  予約の Study Instance UID は撮影の値をそのまま使う。予約の状態は MPPS に合わせ、結び付けた
  後の N-SET は予約の状態を進める
- 確定のときに、ADT^A40（患者 ID が違う）または ADT^A08（患者 ID が同じで属性が違う）と、
  ORM^O01（NW）を、順に送る。受理されなかった 1 通で止める
- 送った本文と結果（送信待ち・送信完了・拒否・送信失敗）を記録し、予約の詳細に出す。
  受理されていない通は、同じ本文で再送信できる
- 画面に「未照合」の一覧と照合の画面を足す。CLI に `reconcile list`・`run`・`resend` を足す
- 照合で作った予約の詳細に、照合前の患者と HL7 送信の表を出す
- `docs/spec/07_reconciliation.md`・ADR-0011 を足し、憲章の対象に照合を足す

## Capabilities

### New Capabilities

- `pir-reconciliation`: 未照合の撮影の一覧、照合の確定、HL7 の送信の記録と再送信、画面と CLI

### Modified Capabilities

（なし）

## Impact

- コード：`app/core/reconciliation.py`（MPPS の読み取りと送る HL7 の決め方）、
  `app/services/reconciliation.py`（照合）、`app/services/store.py`（`reconciliations` の表と
  照合の保存）、`app/web/app.py` とテンプレート、`app/cli/main.py`、`app/core/exceptions.py`
- データベース：`reconciliations` の表を足す（無ければ起動のときに作る。古いデータベースは
  そのまま読める）
- テスト：`tests/core/test_reconciliation.py`・`tests/services/test_reconciliation.py`・
  `tests/web/test_reconciliation.py`・`tests/cli/test_cli_reconcile.py`・`tests/hl7/stub.py`
- ドキュメント：`docs/spec/07_reconciliation.md`（新規）、ADR-0011、`docs/spec/03_web_cli.md`・
  `05_mpps_scp.md`・`06_hl7_pir.md`、`docs/usage.md`、`docs/architecture.md`、
  `docs/project_charter.md`、`docs/README.md`
- 依存：追加しない
- 範囲外：照合の取り消し、DTG が照合の後に元の仮情報で送る追加の画像（IHE の Case 6）の扱い、
  RAD-13（ORM の CA・DC・XO）、A02・A03・A06・A07、v2.5.1、複数の予約を 1 つの撮影に結ぶこと、
  未照合の一覧のページ分け
