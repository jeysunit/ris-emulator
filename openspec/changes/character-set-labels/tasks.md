# Tasks

## 1. 表示の名前

- [ ] 1.1 `app/core/models.py` に `CHARACTER_SET_LABELS` を足し、3つの選択肢すべてに名前があり、どの名前にも `\` と `¥` が無いことを `tests/core/` の試験で確かめる
- [ ] 1.2 Specific Character Set の値の規則（`ISO_IR 192` は値1つ、`ISO 2022` で始まる語を含めば値2つ以上、重なりなし）を3つの選択肢で確かめる試験を `tests/core/test_mwl_dataset.py` に足す
- [ ] 1.3 `jis` の予約の Patient's Name を符号化したバイト列が PS3.5 Example H.3-1 と同じになることを `tests/core/test_mwl_dataset.py` で確かめる

## 2. 画面・エラーの文・CLI

- [ ] 2.1 `app/web/app.py` の `CHARACTER_SET_LABELS` を models.py の名前に替え、予約の画面の選択肢と詳細の「文字コード」に名前が出て、「MWL の属性」には値がそのまま出ることを `tests/web/test_web.py` で確かめる
- [ ] 2.2 `check_encodable` のエラーの文を名前にし、`jis` で `髙` を含む予約のエラーの文を `tests/services/test_order_service.py` で確かめる
- [ ] 2.3 CLI の `--charset` の説明に3つの名前を出し、`python -m app.cli create --help` の出力で確かめる

## 3. ドキュメントと全体の確かめ

- [ ] 3.1 `docs/spec/02_mwl_scp.md` の 5 章の表に表示の名前の列と、規格の照合の結果（design.md の Context）を書き、markdownlint が合格することを確かめる
- [ ] 3.2 `python -m pytest -q` がすべて合格することを確かめる

## Workflow follow-up

- PR のレビューの後に、この change を archive する
