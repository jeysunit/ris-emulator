# Tasks

## 1. 言葉の置き換え

- [x] 1.1 `app/`・`tests/`・`docs/`（`docs/decisions/` を除く）・`openspec/specs/`・`README.md` の「患者 ID」「患者氏名」「AE タイトル」「頁」を直す
- [x] 1.2 一覧の下のページ送りの `aria-label` を「ページ送り」にする（ナビの「ページ」と重ねない）

## 2. 決まりと試験

- [x] 2.1 `openspec/specs/screen-terms/spec.md` に「語の使い分け」の要件を足す
- [x] 2.2 `tests/web/test_web.py` に、外した語が画面に出ないことを確かめる試験を足す
- [x] 2.3 `python -m pytest -q` がすべて合格することを確かめる

## Workflow follow-up

- PR のレビューの後にマージする。この change は、マージのときに archive へ置いた
