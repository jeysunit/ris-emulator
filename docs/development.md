# 開発

## 1. 環境と Python での起動

Python 3.10 以上。テストの依存パッケージ（pytest・httpx）も `requirements.txt` に含まれる。

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Python で直接起動すると、Web 画面（<http://127.0.0.1:8081/>）と MWL（AE タイトル
`RIS_EMU`、`127.0.0.1:11112`）が 127.0.0.1 で待ち受けます。MWL だけを起動するときは
`python -m app.cli mwl serve` を使います
（[spec/03_web_cli.md](spec/03_web_cli.md) の 1 章）。
CLI は `python -m app.cli` で実行します。

```bash
python -m app.web
```

## 2. テスト

```bash
pytest
```

テストは `tests/` の下に、`app/` と同じ構成（`core/`・`services/`・`mwl/`・`cli/`・
`web/`）で置く。照合や識別子の形式のように規格に従う規則は、テストで固定する。

## 3. ドキュメントのチェック

ドキュメントの規則は [README.md の「書き方」](README.md#書き方) にある。

Markdown の形式を確認する（設定は `.markdownlint-cli2.yaml`）。

```bash
npx markdownlint-cli2 "**/*.md" "#.venv" "#.pytest_cache"
```

ADR の最終更新日の記入漏れを、コミットの範囲を指定して検出する。範囲の中で最後に
変更したコミットの日付より「最終更新日」が古いか、行が無ければ終了コード 1 で失敗する。

```bash
python scripts/check_doc_dates.py origin/main..HEAD
```

## 4. 変更の手順

動作を変更するときは、次の順に更新する。各ドキュメントに何を書くかは
[README.md の「書き方」](README.md#書き方) に従う。

1. spec を更新する
2. 設計判断を伴うなら、ADR を作成する
3. コードとテストを更新する
4. 使い方が変わるなら、[usage.md](usage.md) を更新する

## 5. 同梱する htmx のバージョンを上げる

Web 画面の htmx は `app/web/static/` に置いてコミットしている。バージョンを上げる
ときだけ、`scripts/fetch_web_assets.sh` のバージョンと sha256 を変更して実行する。

```bash
bash scripts/fetch_web_assets.sh
```
