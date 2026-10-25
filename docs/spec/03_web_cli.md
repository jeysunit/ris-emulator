# 03. Web 画面・CLI・設定・Docker

## 1. 起動方法

| コマンド | 起動するもの |
|----------|--------------|
| `python -m app.web` | Web 画面と MWL・MPPS の SCP（`web.start_mwl: true` のとき） |
| `python -m app.cli mwl serve` | MWL・MPPS の SCP だけ |
| `python -m app.cli create` など | 予約の操作（データベースを直接読み書きする） |

画面と CLI と MWL・MPPS の SCP は同じ SQLite のファイルを使う
（[ADR-0002](../decisions/0002-sqlite-order-store.md)）。

## 2. CLI

| サブコマンド | 内容 |
|--------------|------|
| `create CT=3 MR=1` | 予約を作成する。`--date`・`--start`・`--interval`・`--patients random/roster`・`--charset`・`--station`（装置の台帳の名前。モダリティごとに1つ、繰り返せる）・`--department`・`--seed`・`--json` |
| `list` | 一覧。`--date`・`--status`・`--modality`・`--json` |
| `show <受付番号>` | 予約の MWL の全属性 |
| `retake <受付番号>` | 撮り直しの予約を作る（`orders.retake_mode` が `new_order` のとき）。`--date`・`--start`・`--json` |
| `status <受付番号> <状態>` | 状態を変更する（`scheduled`・`in_progress`・`completed`・`cancelled`・`discontinued`）。変更できる向きは [01_orders.md](01_orders.md) の 5 章。照合で作った予約を取消・中止にすると ORM^O01（CA・DC）を送り、結果を出す（[07_reconciliation.md](07_reconciliation.md) の 4.3） |
| `mwl serve` | MWL・MPPS の SCP を起動する |
| `pir send --kind a40/a08/orm` | HL7 v2.3.1 のメッセージを組み立て、MLLP で送る。orm の ORC-1 は `--order-control`（NW・CA・DC・XO）。`--dry-run` は組み立てて出すだけ。オプションは [06_hl7_pir.md](06_hl7_pir.md) の 5 章 |
| `reconcile list`・`reconcile run <SOP Instance UID>`・`reconcile resend <受付番号>` | 予約の無い撮影の照合：未照合の一覧、正式な患者と新しい予約を結んで HL7 を送る、受理されていない HL7 の再送信。オプションは [07_reconciliation.md](07_reconciliation.md) の 6 章 |
| `version` | バージョン |

終了コード：0=正常、1=予期しないエラー、2=設定・入力のエラー（変更できない向きへの
状態の変更と、照合済みの撮影の照合を含む）、3=予約・MPPS・照合の記録が無い、
4=MWL のポートで待ち受けられない、
5=HL7 の送信先が AE・AR で断った、6=HL7 の送信先と通信できない・ACK を読めない。

## 3. Web 画面

### 3.1 ページ

| パス | 内容 |
|------|------|
| `/orders` | 予約。予定日の期間（`date_from`・`date_to`、両端を含む 31日まで。指定が無ければ本日）・状態・モダリティで絞り込み、100 件ずつのページ（`page`）に分ける。「本日」「前日」「翌日」で予定日を動かす。患者ID・受付番号（`q`、前後の空白を除いた完全一致）でも検索する。状態の要約の件数は状態以外の条件で数える。受付番号を選ぶと右の区画（`selected`）に補足と操作を出す |
| `/orders/new` | 予約作成（1件）：患者（名簿から選ぶ・新規（架空）。新規の間は名簿の患者の選択肢を選べない）→ 検査（モダリティ・検査名・装置。モダリティを変えると選択肢を出し直す。htmx）→ 予定（予定日・予定時刻。分は `orders.slot_minutes` ごと）→ 依頼（依頼科・文字コード）。「登録」で作り、予約の詳細へ進む |
| `/orders/batch` | 一括作成：モダリティごとの件数（合わせて 200 件まで）と装置（台帳に2台以上あるときだけ。既定は「全装置に振り分け」）、予定日、開始時刻、間隔（1・5・10・15・20・30・60 分。開始時刻の分は間隔ごと。htmx で出し直す）、患者（新規（架空）・名簿から無作為に）、依頼科（既定は「ランダム」）、文字コード |
| `/orders/<受付番号>` | 予約の詳細と MWL の全属性（パンくず・患者バナー・区画の順。戻り先はパンくずの「予約」）。状態を変更する。`orders.retake_mode` が `new_order` なら、実施中・完了・中止の予約から撮り直しの予約を作る。照合で作った予約には、照合前の患者と HL7 の送信の記録、再送信のボタンを出す |
| `/reconciliation` | 未照合の撮影の一覧（予約に結び付いていない MPPS）。行ごとの「照合」で次の画面へ |
| `/reconciliation/<SOP Instance UID>` | 照合：撮影の値、正式な患者、検査名、依頼科。「照合・送信」で予約を作り、HL7 を送る。詳細は [07_reconciliation.md](07_reconciliation.md) の 5 章 |

- 高さ 48px の上の帯に製品名と版、MWL の AEタイトル・待ち受けの状態・アドレスとポートを出す。
  左に幅 208px のナビ（群「業務」、予約・予約作成・一括作成・未照合）を置く。画面の下に帯は置かない
- 予約作成・一括作成は画面の型 C（入力）の形にする。見出しの行、区画（`fieldset` と `legend`。項目の格子は
  2〜3 列、幅は入力フォームの幅の最大 900px。照合も同じ）、操作の行（右端に副「キャンセル」と主「登録」「作成」）の順で、
  必須の項目は項目名の横に「必須」と書く。画面の上の誤りは、左 4px の状態の色・印・文字の知らせにする
- 予定日の期間が逆順のとき、31日を超えるとき、日付として読めないときは理由を表示する（400）。
  `date` は開始日の別名で、`date=all` は受け付けない
- 一覧は予定日時・受付番号・氏名・モダリティ・検査名・状態の 6 列。状態は枠・印・文字の札で示す。
  右の幅 360px の区画には氏名・患者ID・生年月日・性別・予定日時・検査名（コード）・装置・依頼科を出す。
  900px 以下ではナビは上、区画は一覧の下へ回る
- 選択が無いかページ内に無ければ先頭を選ぶ。ページ送りは q・状態・モダリティ・期間を保ち選択を外す。
  空なら区画を出さず、検索の帯と要約、「条件に合う予約はありません。」と「予約作成」を出す
- 区画の「状態を変える」は送信中に選択欄とボタンを押せなくする。成功時は 204 と `HX-Refresh: true` で
  全体を読み直し、失敗時は保存済みの状態へ戻して画面上部にエラーを出す
- 区画と詳細で、完了・取消・中止（終わりの状態）へ変えるときは、送る前に確認の窓（標準の `dialog`）を
  開く。窓には、受付番号・氏名・検査名、戻せないこと、照合で作った予約なら送る ORM^O01（CA・DC）と
  送り先を書く。サーバーは窓の実行が付ける `confirmed=1` が無い終わりの状態への変更を行わない
  （htmx は 400、画面の送信は窓を開いた詳細を出す。openspec の order-status）
- 「詳細を開く」は詳細へ移る。撮り直しは詳細と同じ条件で、本日・空の時刻を送る
- 実装：FastAPI・Jinja2・htmx（v2.0.9。リポジトリに同梱し、バージョンと sha256 を
  `scripts/fetch_web_assets.sh` に固定）。CSS はビルド工程なしで、3 製品で共通の ui-kit の写し
  （`app/web/static/ui-kit/` の `tokens.css`・`components.css`。版は `VERSION`。製品の側で直さず、版が上がったら
  写し直す）の後に、この製品にしか無い部品の差分の `app.css` を読む
- 本文の幅は画面の型ごとに 1 つで、左寄せ：一覧は幅いっぱい、予約の詳細は最大 1200px（`.w-detail`）、
  予約作成・一括作成・照合は最大 900px（`.w-form`）

### 3.2 画面の文言

画面の文言は RIS・PACS で一般的な用語にする（予約、受付番号、
モダリティ、AEタイトル、依頼科、装置、予定、実施中、完了、取消、中止）。説明文は置かない。

題とナビは「予約」「予約作成」「一括作成」「未照合」。検索は「検索」「条件をクリア」、
ページ送りは「前のページ」「次のページ」とする。

DICOM の属性に付ける日本語の名前は、用語の表（`openspec/specs/screen-terms/spec.md`）に
従う。依頼医は Requesting Physician (0032,1032)、紹介医は Referring Physician's Name
(0008,0090) で、取り違えない。表に無い属性（Requested Procedure ID・
Scheduled Procedure Step ID・Study Instance UID など）は英語の属性名のまま出す。

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
| `mwl.ae_title` | `RIS_EMU` | MWL の AEタイトル |
| `mwl.bind_address`・`mwl.port` | `127.0.0.1`・`11112` | MWL の待ち受けアドレスとポート |
| `mwl.statuses` | `[scheduled, in_progress]` | MWL で返す状態 |
| `mwl.max_results` | 1000 | 一致件数の上限 |
| `mwl.require_called_ae_title` | true | Called AE Title を検証する |
| `orders.institution_name` | `TEST HOSPITAL` | 施設名 |
| `orders.accession_prefix` | `RE` | 受付番号の接頭辞（英数字 4 文字まで） |
| `orders.patient_id_prefix` | `RE` | 乱数で生成する患者ID の接頭辞（英数字 8 文字まで） |
| `orders.issuer_namespace` | `RIS_EMU` | Issuer of Patient ID・Issuer of Accession Number Sequence（英数字と `_` で 16 文字まで。空なら返さない。ADR-0005） |
| `orders.default_character_set` | `utf8` | 文字コードの既定値 |
| `orders.roster_path` | `data/patients_sample.yaml` | 名簿 |
| `orders.departments` | 内科など | 依頼科 |
| `orders.retake_mode` | `append` | 撮り直しの扱い：`append`（同じ予約の中で追加。RIS は何もしない）・`new_order`（撮り直しの予約を作る）。[01_orders.md](01_orders.md) の 7 章 |
| `orders.slot_minutes` | 15 | 予約作成の画面の予定時刻の分の刻み（予約枠の刻み）。1・5・10・15・20・30・60 のどれか（60 を割り切る値）。ほかの値は読み込まない（終了コード 2） |
| `orders.modalities.<モダリティ>` | CT・MR・CR・DX・US・MG | `stations`（装置の台帳。`name`・`ae_title`・`station_name`）・`procedures`（`code`・`name`） |
| `web.bind_address`・`web.port` | `127.0.0.1`・`8081` | 画面の待ち受けアドレスとポート |
| `web.start_mwl` | true | 画面のプロセスで MWL も起動する |
| `hl7.host`・`hl7.port` | `127.0.0.1`・`2575` | HL7 の送信先（MLLP）。`pir send` だけが使う |
| `hl7.sending_application`・`hl7.sending_facility` | `RIS_EMU`・`TEST_HOSPITAL` | MSH-3・MSH-4 |
| `hl7.receiving_application`・`hl7.receiving_facility` | `PACS`・`PACS` | MSH-5・MSH-6 |
| `hl7.processing_id` | `P` | MSH-11：`P`・`T`・`D` |
| `hl7.timeout_seconds` | 10 | 接続と ACK を待つ秒数（0 より大きく 300 まで） |

- 相対パスは、プロセスの作業ディレクトリを基準に解決する
- 環境変数 `RIS_WEB_BIND_ADDRESS`・`RIS_MWL_BIND_ADDRESS` があれば、
  `web.bind_address`・`mwl.bind_address` より優先する
- 装置の台帳（`stations`）は、モダリティごとに1台以上を並べる。1台ごとに次の3つを持つ
  - `name`：画面と CLI で選ぶ運用上の名前（例 `CT1号機`）。MWL には入れない。
    空白だけにせず、前後に空白を付けず、64 文字まで。台帳の全体で重ねない
  - `ae_title`：Scheduled Station AE Title (0040,0001) に入れる。PS3.5 6.2 の AE の規則
    （16 文字まで、表示可能な ASCII 文字だけで `\` を含まない、空白だけにしない）で検証する
  - `station_name`：Scheduled Station Name (0040,0010) に入れる。SH の規則（16 文字まで、
    `\` と制御文字を含まない。PS3.5 6.2）で検証する。省略すると空
- 台帳の既定値は、モダリティごとに1台（`CT1号機`・`CT01`・`CT01` など、モダリティ名に
  `1号機`・`01` を付けたもの）。特定の施設の装置を指さない一般的な名前にしている
- 利用者は、`ae_title` をモダリティ側の AEタイトルに変更する。異なると、モダリティが
  自分の AEタイトルで絞り込んだときに予約が返らない
- 古い形のキー（モダリティの直下の `station_ae_titles`・`station_name`）がある設定は、
  `stations` の形を示すエラーで読み込まない（終了コード 2）。古い値から推測して変換しない
  （名前を推測で決めると、画面に出る名前が利用者の意図と違うため）

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
- イメージは GitHub Actions（`.github/workflows/image.yml`）で、テストが成功してから
  `ghcr.io/jeysunit/ris-emulator` に公開する。main への push で `latest` と
  `sha-<コミットの短い hash>`、版のタグ（`v*`）の push で `vX.Y.Z` と `sha-<コミットの短い hash>` を付ける。
  PR ではテストとビルドだけを行い、公開しない
