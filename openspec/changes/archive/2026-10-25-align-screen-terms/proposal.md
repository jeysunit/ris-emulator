# Proposal

## Why

tsunagi-dicom・dicom-test-generator と画面の言葉をそろえる。同じ意味の語が製品ごとに違うと
（患者ID／患者 ID、氏名／患者氏名）、使う人は別の項目だと読む。3 製品の画面の言葉の決まりが
できたので、ris-emulator の画面・CLI・文書の言葉を、その決まりに合わせる。

## What Changes

- 「患者 ID」を「患者ID」にする。「AE タイトル」を「AEタイトル」にする（語の中の空白をなくす）
- 「患者氏名」を「氏名」にする
- 「頁」を「ページ」にする。一覧の下のページ送りの `aria-label` は、ナビの「ページ」と重ならないよう「ページ送り」にする
- `screen-terms` に、語の使い分けの要件（語の中の空白、氏名、ページ、標準と初期設定）を足す
- 用語の表と、`order-list`・`order-entry`・`retake`・`stations`・`mpps-scp`・`hl7-sender` の spec と
  `docs/spec/` の同じ語を、上の言葉に直す。振る舞いと値は変えない

## Capabilities

### New Capabilities

（なし）

### Modified Capabilities

- `screen-terms`: 患者と依頼の属性の名前（患者ID・氏名）、予定の属性の名前（予定のAEタイトル）、語の使い分けの要件を足す
- `order-list`・`order-entry`・`retake`・`stations`・`mpps-scp`・`hl7-sender`: 言葉だけを直す（要件の意味は変えない）。
  差分の spec は置かず、`openspec/specs/` の各ファイルを直接直した

## Impact

- コード：`app/web/templates/`（一覧・詳細・照合の見出しと項目の名前、ページ送り）、`app/web/app.py`・`app/cli/main.py`・`app/core/`・`app/services/` の画面・CLI に出る誤りの文
- 試験：言葉に合わせて期待の文字を直した（`tests/web/`・`tests/cli/` ほか）。語が画面に出ないことを確かめる `test_pages_avoid_retired_words` を足した
- 文書：`docs/spec/`・`docs/usage.md`・`README.md`・`docs/development.md`・`docs/project_charter.md`。判断の記録（`docs/decisions/`）と過去の change（`openspec/changes/archive/`）は、当時の書き方のまま残す
