# 構成

ris-emulator は1つの Python パッケージ（`app/`）で構成する。Web 画面・CLI・MWL と
MPPS の SCP の3つが、同じ SQLite のファイルに予約を読み書きする。

## 1. プロセスと保存先

```mermaid
flowchart LR
  subgraph proc1["python -m app.web"]
    WEB["Web 画面<br/>FastAPI"]
    MWL["MWL・MPPS の SCP<br/>pynetdicom"]
  end
  CLI["python -m app.cli"]
  DB[("SQLite<br/>state/ris.sqlite3")]
  MOD["モダリティ"]
  WEB <-->|"予約（読み書き）"| DB
  CLI <-->|"予約（読み書き）"| DB
  DB <-->|"予約・MPPS の記録（読み書き）"| MWL
  MWL -->|"ワークリスト（C-FIND の応答）"| MOD
  MOD -->|"撮影の開始・完了・中止（MPPS の N-CREATE・N-SET）"| MWL
```

- `python -m app.web` は、Web 画面と MWL・MPPS の SCP を1つのプロセスで実行する
  （`web.start_mwl: true` のとき）。MWL だけを実行するときは `python -m app.cli mwl serve`
- CLI は別のプロセスとして実行し、データベースを直接読み書きする
- 同時の書き込みは、SQLite のロックとトランザクションで保護する
  （[ADR-0002](decisions/0002-sqlite-order-store.md)）

## 2. 層

```text
Web (app/web/) ─┐
CLI (app/cli/) ─┤→ Service (app/services/) → Core (app/core/)
MWL (app/mwl/) ─┘
```

- Core：予約のモデル、患者の生成、照合、応答の組み立て、文字コードの検証。
  ファイル・通信・ログを使わない
- Service：設定・名簿の読み込み、予約と MPPS の記録の保存（SQLite）、予約の作成
- Web・CLI・MWL：外部からの操作を受け付ける。予約の保存と作成は Service を経由し、
  Core のモデルと、照合・応答の組み立ての関数は直接呼び出す

照合と応答の組み立てを Core に置くのは、通信なしでテストするためである
（[ADR-0001](decisions/0001-mwl-scp-with-pynetdicom.md)）。

## 3. ディレクトリ

| 場所 | 内容 |
|------|------|
| `app/core/` | 予約のモデル、患者の生成、MWL の照合と応答の組み立て、文字コードの検証 |
| `app/services/` | 設定・名簿の読み込み、予約の保存（SQLite）、予約の作成 |
| `app/mwl/` | MWL と MPPS の SCP（pynetdicom） |
| `app/cli/` | CLI |
| `app/web/` | Web 画面（テンプレート・CSS・htmx を含む） |
| `config/` | 設定の例（`app_config.yaml`） |
| `data/` | 名簿の例（架空の患者） |
| `scripts/` | 同梱する htmx の取得スクリプト、ADR の最終更新日の検証スクリプト |
| `tests/` | テスト。`app/` と同じ構成に分ける |
| `docs/` | ドキュメント（[README](README.md) が索引） |
| `.github/workflows/` | テストと、GHCR へのイメージの公開（`image.yml`） |
