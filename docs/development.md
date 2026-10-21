# 開発

- 作成日：2026-10-21
- 最終更新日：2026-10-22

## 1. 環境

Python 3.10 以上。テストの依存パッケージ（pytest・httpx）も `requirements.txt` に含まれる。

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## 2. テスト

```bash
pytest
```

テストは `tests/` の下に、`app/` と同じ構成（`core/`・`services/`・`mwl/`・`cli/`・
`web/`）で置く。照合や識別子の形式のように規格に従う規則は、テストで固定する。

## 3. ドキュメントのチェック

```bash
npx markdownlint-cli2 "**/*.md" "#.venv" "#.pytest_cache"
```

ルールは `.markdownlint-cli2.yaml` にある（本文は 80 文字で折り返す）。

ドキュメントを更新したら、冒頭の「最終更新日」をその日付に更新する
（[README.md](README.md) の「冒頭の日付」）。記入漏れは、コミットの範囲を指定して検出する。

```bash
python scripts/check_doc_dates.py origin/main..HEAD
```

範囲の中で追加・変更したドキュメント（ルートの README.md と docs/ の下の .md。
ADR を除く）ごとに、範囲の中で最後にそのドキュメントを変更したコミットを調べる。
そのコミット時点の「最終更新日」がコミットの日付より古いか、行が無ければ失敗する
（終了コード 1）。

## 4. 変更の手順

動作を変更するときは、次の順に更新する。

1. spec を更新する。spec は現在の動作を書くドキュメントなので、コードと同じ PR で
   更新し、常に現在の動作に合わせておく
2. 設計判断（方式の選択、規格が許す形式のうちどれを選ぶか）を伴うなら、ADR を
   作成する。書き方は [decisions/README.md](decisions/README.md) にある
3. コードとテストを更新する
4. 使い方が変わるなら、ルートの README を更新する

規格に従う箇所は、spec に規格の節番号を書く
（[project_charter.md](project_charter.md) の 3 章）。

## 5. 同梱する htmx のバージョンを上げる

Web 画面の htmx は `app/web/static/` に置いてコミットしている。バージョンを上げる
ときだけ、`scripts/fetch_web_assets.sh` のバージョンと sha256 を変更して実行する。

```bash
bash scripts/fetch_web_assets.sh
```
