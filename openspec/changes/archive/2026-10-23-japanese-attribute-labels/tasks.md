# Tasks

## 1. 用語の照合

- [x] 1.1 design.md の一覧の名前を、JIRA の公開の文書（JJ1017 の指針など）の用語と照らし、違いがあれば一覧の「見立て」に書く（差があっても、明らかな誤りでなければ名前は変えない）

## 2. 文書と試験

- [x] 2.1 `docs/spec/01_orders.md` の 1 章の表の「依頼医」の行を、依頼医（Requesting Physician (0032,1032)）と紹介医（Referring Physician's Name (0008,0090)）の2行に分け、`git grep -n "依頼医\|紹介医" docs` で2つの属性の取り違えが無いことを確かめる
- [x] 2.2 `docs/spec/03_web_cli.md` の 3.2 に用語の表（`openspec/specs/screen-terms/spec.md`）への参照を書き、markdownlint が合格することを確かめる
- [x] 2.3 予約の一覧の見出しと詳細の項目の名前が用語の表と一致することを `tests/web/test_web.py` で確かめ、`python -m pytest -q` がすべて合格することを確かめる

## Workflow follow-up

- PR のレビューの後に、この change を archive する
