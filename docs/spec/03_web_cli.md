# 03. Web 画面・CLI・設定・Docker

- 作成日：2026-10-21
- 最終更新日：2026-10-22

## 1. 起動方法

| コマンド | 起動するもの |
|----------|--------------|
| `python -m app.web` | Web 画面と MWL の SCP（`web.start_mwl: true` のとき） |
| `python -m app.cli mwl serve` | MWL の SCP だけ |
| `python -m app.cli create` など | 予約の操作（データベースを直接読み書きする） |

画面と CLI と MWL は同じ SQLite のファイルを使う
（[ADR-0002](../decisions/0002-sqlite-order-store.md)）。

## 2. CLI

| サブコマンド | 内容 |
|--------------|------|
| `create CT=3 MR=1` | 予約を作成する。`--date`・`--start`・`--interval`・`--patients random/roster`・`--charset`・`--station-ae`・`--department`・`--seed`・`--json` |
| `list` | 一覧。`--date`・`--status`・`--modality`・`--json` |
| `show <受付番号>` | 予約の MWL の全属性 |
| `status <受付番号> <状態>` | 状態を変更する（`scheduled`・`in_progress`・`completed`・`cancelled`） |
| `mwl serve` | MWL の SCP を起動する |
| `version` | バージョン |

終了コード：0=正常、1=予期しないエラー、2=設定・入力のエラー、3=予約が無い、
4=MWL のポートで待ち受けられない。

## 3. Web 画面

### 3.1 ページ

| パス | 内容 |
|------|------|
| `/orders` | 予約の一覧（予定日・状態・モダリティで絞り込む）。行ごとに状態を選んで変更する（htmx） |
| `/orders/new` | 予約の作成：モダリティごとの件数、予定日、開始時刻、間隔、予定の AE タイトル、患者（乱数・名簿）、依頼科、文字コード、シード |
| `/orders/<受付番号>` | 予約の詳細と MWL の全属性。状態を変更する |

- 画面上部のバーに、MWL の AE タイトル、待ち受けの状態、アドレスとポートを表示する
- 実装：FastAPI・Jinja2・htmx（v2.0.9。リポジトリに同梱し、バージョンと sha256 を
  `scripts/fetch_web_assets.sh` に固定）。CSS は手書きの1ファイル（ビルド工程なし）

### 3.2 画面の文言

画面の文言は RIS・PACS で一般的な用語にする（予約、受付番号、
モダリティ、AE タイトル、依頼科、予定、実施中、完了、取消）。説明文は置かない。

### 3.3 セキュリティ

理由は [ADR-0006](../decisions/0006-web-ui-loopback-by-default.md) にある。

- 既定は 127.0.0.1 だけで待ち受け、認証は設けない。`Host` ヘッダーが
  ループバックの名前でなければ拒否する（DNS rebinding 対策）
- ループバック（127.0.0.0/8・`::1`・`localhost`）以外で待ち受けるときは
  HTTP Basic 認証を必須にする。パスワードは、
  環境変数 `RIS_WEB_PASSWORD_FILE` が指すファイルから起動時に1回読み込む。
  ファイルが無い、または読み取れないときは起動しない（終了コード 2）。ユーザー名は `ris`
- 書き込み（POST）は、`Origin`（無ければ `Referer`）が同一 origin で、
  起動のたびに生成する CSRF トークンが送られたときだけ受け付ける
- 応答に CSP（`default-src 'self'`、インラインスクリプトなし）などのヘッダーを付ける

## 4. 設定（`config/app_config.yaml`）

| キー | 既定値 | 内容 |
|------|--------|------|
| `database` | `state/ris.sqlite3` | 予約のデータベース |
| `mwl.ae_title` | `RIS_EMU` | MWL の AE タイトル |
| `mwl.bind_address`・`mwl.port` | `127.0.0.1`・`11112` | MWL の待ち受けアドレスとポート |
| `mwl.statuses` | `[scheduled, in_progress]` | MWL で返す状態 |
| `mwl.max_results` | 1000 | 一致件数の上限 |
| `mwl.require_called_ae_title` | true | Called AE Title を検証する |
| `orders.institution_name` | `TEST HOSPITAL` | 施設名 |
| `orders.accession_prefix` | `RE` | 受付番号の接頭辞（英数字 4 文字まで） |
| `orders.patient_id_prefix` | `RE` | 乱数で生成する患者 ID の接頭辞（英数字 8 文字まで） |
| `orders.issuer_namespace` | `RIS_EMU` | Issuer of Patient ID・Issuer of Accession Number Sequence（英数字と `_` で 16 文字まで。空なら返さない。ADR-0005） |
| `orders.default_character_set` | `utf8` | 文字コードの既定値 |
| `orders.roster_path` | `data/patients_sample.yaml` | 名簿 |
| `orders.departments` | 内科など | 依頼科 |
| `orders.modalities.<モダリティ>` | CT・MR・CR・DX・US・MG | `station_ae_titles`・`station_name`・`procedures`（`code`・`name`） |
| `web.bind_address`・`web.port` | `127.0.0.1`・`8081` | 画面の待ち受けアドレスとポート |
| `web.start_mwl` | true | 画面のプロセスで MWL も起動する |

- 相対パスは、プロセスの作業ディレクトリを基準に解決する
- 環境変数 `RIS_WEB_BIND_ADDRESS`・`RIS_MWL_BIND_ADDRESS` があれば、
  `web.bind_address`・`mwl.bind_address` より優先する
- 予定の AE タイトル（`station_ae_titles`）の既定値は、モダリティ名に `01` を
  付けたもの（`CT01`・`MR01`・`CR01`・`DX01`・`US01`・`MG01`）。特定の施設の装置を
  指さない一般的な名前にしている。値は PS3.5 の AE の規則（16 文字まで、表示可能な
  ASCII 文字だけで `\` を含まない、空白だけにしない）で検証する
- 利用者は、この値をモダリティ側の AE タイトルに変更する。異なると、モダリティが
  自分の AE タイトルで絞り込んだときに予約が返らない

## 5. Docker

- ベースイメージは `python:3.12-slim-trixie`（digest で固定）
- root 以外のユーザー（`ris`、uid 10001）で実行する。書き込むのは `/app/state` だけ
- `CMD` は `python -m app.web`（画面と MWL を1つのコンテナで実行する）
- イメージは環境変数 `RIS_WEB_BIND_ADDRESS=0.0.0.0`・`RIS_MWL_BIND_ADDRESS=0.0.0.0` を
  設定済みで、設定ファイルをマウントしなくても外部から接続できる。
  `RIS_WEB_PASSWORD_FILE` でパスワードのファイルを指定する。ファイルは uid 10001 が
  読み取れる権限にする（例 `chmod 0444`）
- 予定日（`today`）と時刻はローカル時刻（`TZ`）で決まる。`TZ` を
  モダリティ側と合わせる（例 `TZ=Asia/Tokyo`）。ベースイメージに
  tzdata が含まれることを確認済み（`/usr/share/zoneinfo/Asia/Tokyo`）
