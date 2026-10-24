# Proposal

## Why

予約の無い撮影（緊急の飛び込みなど）は、仮の患者 ID で撮られた画像が PACS に届く。
後で正式な患者と予約が決まると、PACS に「仮 ID の検査を正式な患者 ID に付け替える」と
知らせる必要がある。IHE の PIR（Patient Information Reconciliation）では、RIS（Department
System Scheduler/Order Filler）がその知らせを HL7 v2 で送る。ris-emulator は今、HL7 を
送れないので、PACS の PIR への対応を試す相手にならない。

この change は、そのうち HL7 v2.3.1 のメッセージの組み立てと送信だけを作る。照合の画面と
未照合の MPPS の一覧は、後の change で作る。

## What Changes

- ADT^A40（患者 ID の統合）・ADT^A08（患者の属性の更新）・ORM^O01（予約。ORC-1 は NW）を、
  IHE RAD TF-2 の 4.12・4.4 に従って組み立てる。区切り文字はエスケープし、漢字の氏名は
  UTF-8（MSH-18）で送る
- MLLP で設定の宛先へ送り、ACK の MSA-1 で「受理（AA）」「拒否（AE・AR）」「失敗
  （接続・枠・ACK の誤り）」に分ける
- 設定に `hl7` の節（宛先と MSH の名前）を足す
- CLI に `pir send --kind a40|a08|orm`（`--dry-run` で組み立てだけ）を足す
- 3 つのメッセージの例を docs に書く（受け手の tsunagi と共有するため）
- `docs/project_charter.md` の対象に「HL7 v2 の送信」を足す。受信は対象外のまま

## Capabilities

### New Capabilities

- `hl7-sender`: PIR の HL7 v2.3.1 メッセージの組み立て、MLLP での送信、ACK の扱い、宛先の設定、CLI

### Modified Capabilities

（なし）

## Impact

- コード：`app/core/hl7.py`（組み立てと ACK の読み取り）、`app/hl7/mllp.py`（送信）、
  `app/services/config.py`（`hl7` の節）、`app/cli/main.py`（`pir send`）、
  `app/core/exceptions.py`
- 設定：`config/app_config.yaml` に `hl7` の節を足す。無い設定ファイルは既定値で読める
- テスト：`tests/hl7/`（組み立て、MLLP とスタブの受け手）、`tests/cli/test_cli_pir.py`、
  `tests/services/test_hl7_config.py`
- ドキュメント：`docs/spec/06_hl7_pir.md`（新規）、`docs/spec/03_web_cli.md`、`docs/usage.md`、
  `docs/architecture.md`、`docs/project_charter.md`、ADR-0010
- 依存：追加しない
- 範囲外：HL7 の受信、A02・A03・A06・A07、RAD-13 の CA・DC・XO、v2.5.1（OMI）、
  照合の画面、未照合の MPPS の一覧、送信結果の保存と再送
