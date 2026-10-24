# Tasks

## 1. メッセージの組み立て

- [x] 1.1 `app/core/hl7.py` に `escape`・`unescape`・MSH の組み立てを書き、区切り文字の往復と制御文字の拒否を `tests/hl7/test_messages.py` で確かめる
- [x] 1.2 ADT^A40 を組み立て、PID に正式 ID、MRG に旧 ID が入ること、旧 ID が空か同じなら断ることを試験で確かめる
- [x] 1.3 ADT^A08 を組み立て、PID-18 か PV1-19 が無ければ断ることを試験で確かめる
- [x] 1.4 ORM^O01 を組み立て、ORC-1 が NW、OBR-18〜20・ZDS-1 に ADR-0003 の識別子がそのまま入ることを試験で確かめる
- [x] 1.5 氏名の XPN（接頭辞と接尾辞の入れ替え、3 表記の繰り返し）と、漢字のときだけ MSH-18 を入れることを試験で確かめる

## 2. MLLP と ACK

- [x] 2.1 `parse_ack` を書き、AA・AE・AR、ERR、LF 区切り、読めない入力を試験で確かめる
- [x] 2.2 `app/hl7/mllp.py` の送信を書き、スタブの受け手で AA・AE・AR・MSA-2 の不一致・想定外のコード・接続拒否・接続の切断・枠の誤り・時間切れ・大きすぎる ACK を `tests/hl7/test_mllp.py` で確かめる

## 3. 設定と CLI

- [x] 3.1 `hl7` の節を `app/services/config.py` と `config/app_config.yaml` に足し、範囲外の値と節が無い設定を `tests/services/test_hl7_config.py` で確かめる
- [x] 3.2 `pir send` を書き、`--dry-run`・受理・拒否（5）・通信の失敗（6）・入力の誤り（2）・予約が無い（3）を `tests/cli/test_cli_pir.py` で確かめる

## 4. ドキュメント

- [x] 4.1 `docs/spec/06_hl7_pir.md`（3 つの例を含む）・ADR-0010・`docs/spec/03_web_cli.md`・`docs/usage.md`・`docs/architecture.md`・`docs/project_charter.md` を直し、markdownlint が合格することを確かめる
- [ ] 4.2 `python -m pytest -q` がすべて合格し、CI が緑であることを確かめる

## Workflow follow-up

- PR のレビューの後に、この change を archive する
