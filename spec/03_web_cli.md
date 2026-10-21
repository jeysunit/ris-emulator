# 03. Web 画面・CLI・設定

## 1. 起動の形

| コマンド | 動くもの |
|----------|----------|
| `python -m app.web` | Web 画面と MWL の SCP（`web.start_mwl: true` のとき） |
| `python -m app.cli mwl serve` | MWL の SCP だけ |
| `python -m app.cli create` など | 予約の操作（保存先を直に読み書きする） |

画面と CLI と MWL は同じ SQLite のファイルを使う（ADR-0002）。

## 2. CLI

| サブコマンド | 中身 |
|--------------|------|
| `create CT=3 MR=1` | 予約を作る。`--date`・`--start`・`--interval`・`--patients random/roster`・`--charset`・`--station-ae`・`--department`・`--seed`・`--json` |
| `list` | 一覧。`--date`・`--status`・`--modality`・`--json` |
| `show <受付番号>` | 予約の MWL の全属性 |
| `status <受付番号> <状態>` | 状態を変える（`scheduled`・`in_progress`・`completed`・`cancelled`） |
| `mwl serve` | MWL の SCP を起動する |
| `version` | 版 |

終了コード：0=正常、1=予期しない誤り、2=設定・入力の誤り、3=予約が無い、
4=MWL を待ち受けられない。

## 3. Web 画面

### 3.1 ページ

| パス | 中身 |
|------|------|
| `/orders` | 予約の一覧（予定日・状態・モダリティで絞る）。行ごとに状態を選んで変える（htmx） |
| `/orders/new` | 予約を作る：モダリティごとの件数、予定日、開始時刻、間隔、予定の AE タイトル、患者（乱数・名簿）、依頼科、文字コード、シード |
| `/orders/<受付番号>` | 予約の詳細と MWL の全属性。状態を変える |

- 上の帯に MWL の AE タイトル、待ち受けの状態、アドレスとポートを出す
- 作り方は dicom-test-generator の画面と同じ：FastAPI・Jinja2・htmx（v2.0.9、
  リポジトリに置き、版と sha256 を `scripts/fetch_web_assets.sh` に固定）。
  CSS は手で書いた1ファイル（ビルドの工程を持たない）

### 3.2 文言

画面の文言は RIS・PACS でふつうに使う用語にする（予約、受付番号、
モダリティ、AE タイトル、依頼科、予定、実施中、完了、取消）。説明の文は置かない。

### 3.3 安全（dicom-test-generator の spec/12a 10.9 と同じ決まり）

- 既定は 127.0.0.1 だけで待ち受け、認証は付けない。`Host` ヘッダーが
  ループバックの名前でなければ断る（DNS rebinding よけ）
- 127.0.0.1 以外で待ち受けるときは HTTP Basic を必須にする。パスワードは
  環境変数 `RIS_WEB_PASSWORD_FILE` が指すファイルから起動のときに1回読む。
  無い・読めないときは起動しない（終了コード 2）。ユーザー名は `ris`
- 書き込み（POST）は、`Origin`（無ければ `Referer`）が同じ origin で、
  起動のたびに作る CSRF の token を返したときだけ受ける
- 応答に CSP（`default-src 'self'`、インラインのスクリプトなし）などのヘッダーを付ける

## 4. 設定（`config/app_config.yaml`）

| キー | 既定 | 中身 |
|------|------|------|
| `database` | `state/ris.sqlite3` | 予約の保存先 |
| `mwl.ae_title` | `RIS_EMU` | MWL の AE タイトル |
| `mwl.bind_address`・`mwl.port` | `127.0.0.1`・`11112` | MWL の待ち受け |
| `mwl.statuses` | `[scheduled, in_progress]` | MWL で返す状態 |
| `mwl.max_results` | 1000 | 一致の件数の上限 |
| `mwl.require_called_ae_title` | true | Called AE Title を確かめる |
| `orders.institution_name` | `TEST HOSPITAL` | 施設名 |
| `orders.accession_prefix` | `RE` | 受付番号の接頭辞（英数字 4 字まで） |
| `orders.patient_id_prefix` | `RE` | 乱数の患者 ID の接頭辞（英数字 8 字まで） |
| `orders.issuer_namespace` | `RIS_EMU` | Issuer of Patient ID・Issuer of Accession Number Sequence（英数字と `_` で 16 字まで。空なら返さない。spec/04） |
| `orders.default_character_set` | `utf8` | 文字コードの既定 |
| `orders.roster_path` | `data/patients_sample.yaml` | 名簿 |
| `orders.departments` | 内科など | 依頼科 |
| `orders.modalities.<モダリティ>` | CT・MR・CR・DX・US・MG | `station_ae_titles`・`station_name`・`procedures`（`code`・`name`） |
| `web.bind_address`・`web.port` | `127.0.0.1`・`8081` | 画面の待ち受け |
| `web.start_mwl` | true | 画面のプロセスで MWL も立てる |

- 相対のパスは、プロセスの作業ディレクトリから辿る
- 環境変数 `RIS_WEB_BIND_ADDRESS`・`RIS_MWL_BIND_ADDRESS` があれば、
  `web.bind_address`・`mwl.bind_address` より先に効く
- 既定の予定の AE タイトルは dicom-test-generator の既定（`DTG_CT01`）に合わせ、
  設定を変えずに TDG がワークリストを取得できるようにしている

## 5. Docker

- ベースイメージは dicom-test-generator と同じ `python:3.12-slim-trixie`（digest で固定）
- root 以外のユーザー（`ris`、uid 10001）で動かす。書き込むのは `/app/state` だけ
- `CMD` は `python -m app.web`（画面と MWL を1つのコンテナで）
- イメージは `RIS_WEB_BIND_ADDRESS=0.0.0.0`・`RIS_MWL_BIND_ADDRESS=0.0.0.0` を持ち、
  設定ファイルを mount しなくても外から届く。`RIS_WEB_PASSWORD_FILE` で
  パスワードのファイルを渡す。ファイルは uid 10001 が読める権限にする（例 `chmod 0444`）
- 予定の日（`today`）と時刻はローカル時刻（`TZ`）で決まる。`TZ` を
  dicom-test-generator とそろえる（例 `TZ=Asia/Tokyo`）。ベースイメージに
  tzdata が入っていることを確かめた（`/usr/share/zoneinfo/Asia/Tokyo`）
