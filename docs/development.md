# 開発

## 1. 環境と Python での起動

Python 3.10 以上。テストの依存パッケージ（pytest・httpx）も `requirements.txt` に含まれる。

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Python で直接起動すると、Web 画面（<http://127.0.0.1:8081/>）と MWL（AEタイトル
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

## 6. 版の付け方

- **版の正は git のタグ（`vX.Y.Z`、Semantic Versioning）。** コードの中に版の定数は持たない。版を上げるのは、タグを付けることだけ。
- 画面「管理 → バージョン情報」と CLI の `version` は、イメージを作るときに `scripts/app-version.sh` が git から作った版を出す。
  - タグの上：`0.2.0`（`v` を除く）。
  - タグより後：`0.2.0+37.g60970f9`（SemVer のビルドの印。直近のタグからの commit の数と、短い commit）。
  - タグが 1 つも無い：`0.0.0+37.g60970f9`（commit の数と短い commit）。
  - git の情報が無い（`.git` の無い場所での build）：`0.0.0+unknown`。何から作ったか分からない印。
- 作った値は `APP_VERSION` の build-arg でイメージに渡す。`.git` はイメージの文脈に入らないので、イメージの中では作れない。image.yml は `fetch-depth: 0` でタグまで取ってから作る。履歴の浅い checkout ではタグが取れず、「タグが 1 つも無い」の形になる。
- 手元で `python -m app.web` や `python -m app.cli` を起こすときは、`APP_VERSION` が無ければ作業ツリーの git から同じ値を作る。
- 本番へは、タグの版（`0.2.0` の形）のイメージだけを置く。`+` の付いた版は、タグより後の作りで、試す環境のためのもの。
- 版を出すとき：`main` の取り込み済みの commit に `git tag vX.Y.Z` を付けて push する（image.yml が `vX.Y.Z` のイメージを作る）。付けたタグは動かさない・消さない。
