# 開発

## 1. 環境

Python 3.10 以上。試験の依存（pytest・httpx）も `requirements.txt` に入っている。

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## 2. 試験

```bash
pytest
```

試験は `tests/` の下に、`app/` と同じ並び（`core/`・`services/`・`mwl/`・`cli/`・
`web/`）で置く。照合や識別子の形のように規格に従う決まりは、試験で固定する。

## 3. 文書の確かめ

```bash
npx markdownlint-cli2 "**/*.md" "#.venv" "#.pytest_cache"
```

決まりは `.markdownlint-cli2.yaml` にある（本文は 80 字で折り返す）。

## 4. 変更の進め方

振る舞いを変えるときは、次の順に直す。

1. spec を直す。spec は今どう動くかを書く文書なので、コードと同じ PR で直し、
   いつも今の振る舞いに合わせておく
2. 設計の判断（方式の選択、規格が許す形のどれを選ぶか）を伴うなら、ADR を起こす。
   書き方は [decisions/README.md](decisions/README.md) にある
3. コードと試験を直す
4. 使い方が変わるなら、ルートの README を直す

規格に従う箇所は、spec に規格の節番号を書く
（[project_charter.md](project_charter.md) の 3 章）。

## 5. 同梱する htmx の版を上げる

Web 画面の htmx は `app/web/static/` に置いて commit している。版を上げるときだけ、
`scripts/fetch_web_assets.sh` の版と sha256 を直して流す。

```bash
bash scripts/fetch_web_assets.sh
```
