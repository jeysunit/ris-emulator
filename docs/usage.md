# 使い方

ris-emulator を Docker で起動し、モダリティからワークリストを取得できるようにするまでの手順です。
コマンドの引数と設定の項目の一覧は [spec/03_web_cli.md](spec/03_web_cli.md) にあります。
Python で直接起動する方法は、開発する人向けに [development.md](development.md) にあります。

## 1. 起動する

Docker イメージは `0.0.0.0` で待ち受けるため、HTTP Basic 認証のパスワードの
ファイルが必要です。ファイルはコンテナの uid 10001 が読み取れる権限にします
（[spec/03_web_cli.md](spec/03_web_cli.md) の 3.3 と 5 章）。

1. パスワードのファイルを作成する

   ```bash
   mkdir -p "$HOME/ris-emulator"
   head -c 24 /dev/urandom | base64 > "$HOME/ris-emulator/password"
   chmod 0444 "$HOME/ris-emulator/password"
   ```

2. GHCR のイメージを取得して起動する。予約は名前付きボリューム `ris-state` に保存する

   ```bash
   docker pull ghcr.io/jeysunit/ris-emulator:latest
   docker run -d --name ris-emulator \
     -p 127.0.0.1:8081:8081 -p 127.0.0.1:11112:11112 \
     -e TZ=Asia/Tokyo \
     -e RIS_WEB_PASSWORD_FILE=/run/secrets/ris_web_password \
     -v "$HOME/ris-emulator/password:/run/secrets/ris_web_password:ro" \
     -v ris-state:/app/state \
     ghcr.io/jeysunit/ris-emulator:latest
   ```

Web 画面（<http://127.0.0.1:8081/>、ユーザー名 `ris`）と MWL（AEタイトル `RIS_EMU`、
`127.0.0.1:11112`）が起動します。

`TZ` はモダリティ側と合わせます。予定日（`today`）と時刻はコンテナのローカル時刻で
決まるためです。

### イメージのタグ

| タグ | 内容 |
|------|------|
| `latest` | main ブランチの最新 |
| `vX.Y.Z` | リリースの版 |
| `sha-<コミットの短い hash>` | 特定のコミット |

### Docker Compose で起動する

`secrets` の `file:` はローカルのファイルを元の権限のままコンテナにマウントするので、
こちらも uid 10001 が読み取れる権限にします。`container_name` を指定しておくと、
以降の `docker exec ris-emulator ...` がそのまま使えます。

```yaml
services:
  ris:
    image: ghcr.io/jeysunit/ris-emulator:latest
    container_name: ris-emulator
    environment:
      TZ: Asia/Tokyo
      RIS_WEB_PASSWORD_FILE: /run/secrets/ris_web_password
    secrets:
      - ris_web_password
    volumes:
      - ris-state:/app/state
    ports:
      - "127.0.0.1:8081:8081"
      - "127.0.0.1:11112:11112"

secrets:
  ris_web_password:
    file: ./secrets/ris_web_password.txt   # chmod 0444 にする

volumes:
  ris-state:
```

### イメージを自分でビルドする

リポジトリのソースからイメージを作るときは、`docker pull` の代わりに次を実行し、
`docker run` の最後のイメージ名を `ris-emulator` にします。Compose では `image:` の
代わりに `build: .` と書きます。

```bash
docker build -t ris-emulator .
```

## 2. 設定を変更する

設定ファイルは、イメージの中の `/app/config/app_config.yaml` です。項目の一覧と既定値は
[spec/03_web_cli.md](spec/03_web_cli.md) の 4 章にあります。

設定を変更するときは、リポジトリの `config/app_config.yaml` をコピーして編集し、
`-v "$HOME/ris-emulator/app_config.yaml:/app/config/app_config.yaml:ro"` を
`docker run` に追加してマウントします。

## 3. モダリティを接続する

モダリティの MWL の設定（SCU）で、接続先を次のように設定します。MPPS を送る
モダリティは、MPPS の送り先にも同じ値を設定します。

| 項目 | 値 |
|------|----|
| Called AE Title | `RIS_EMU` |
| ホスト | ris-emulator を実行しているホスト（ローカルなら `127.0.0.1`） |
| ポート | `11112` |

モダリティが自分の AEタイトルで絞り込んで問い合わせる場合は、設定の装置の台帳
`orders.modalities.<モダリティ>.stations` の `ae_title` をモダリティの AEタイトルに
変更します。装置が複数あれば、台帳に並べます（既定値と規則は
[spec/03_web_cli.md](spec/03_web_cli.md) の 4 章）。

```yaml
orders:
  modalities:
    CT:
      stations:
        - {name: "CT1号機", ae_title: "CT01", station_name: "CT01"}
        - {name: "CT2号機", ae_title: "CT02", station_name: "CT02"}
```

予約を作るときは、画面の「装置」か、CLI の `--station CT2号機` で装置を名前で選びます。
一括作成と CLI で選ばなければ、台帳の装置を順に使います。

## 4. 予約を作成する

CLI をコンテナの中で実行して作成します。Web 画面では、1件ずつなら「予約作成」
（`/orders/new`）、件数を指定してまとめて作るなら「一括作成」（`/orders/batch`）を使います。

```bash
# 今日の CT を 3 件、MR を 1 件（09:00 から 15 分おき）
docker exec ris-emulator python -m app.cli create CT=3 MR=1

# 明日の 13:00 から、名簿の患者で CR を 2 件、文字コードは JIS
docker exec ris-emulator python -m app.cli create CR=2 --date tomorrow --start 13:00 --patients roster --charset jis
```

引数の一覧は [spec/03_web_cli.md](spec/03_web_cli.md) の 2 章と `--help` にあります。
文字コードごとに書ける文字の制限は [spec/01_orders.md](spec/01_orders.md) の 3.3 にあります。

## 5. 予約を確認し、状態を変更する

```bash
docker exec ris-emulator python -m app.cli list --date today
docker exec ris-emulator python -m app.cli show RE202610210001
docker exec ris-emulator python -m app.cli status RE202610210001 in_progress
```

Web 画面の `/orders` でも確認・変更できます。完了・取消・中止にした予約は MWL で
返しません。完了・取消・中止は終わりの状態で、ほかの状態に戻せません。やり直すときは
新しい予約を作成してください（[spec/01_orders.md](spec/01_orders.md) の 5 章）。

モダリティが MPPS を送ると、予約は撮影の開始で実施中に、完了で完了に、中止で中止に
なります。受けた MPPS は予約の詳細に表示します
（[spec/05_mpps_scp.md](spec/05_mpps_scp.md)）。MPPS の記録は消しません。初期化するときは
データベースのファイル（コンテナではボリューム `ris-state`）を作り直します。

## 6. 撮り直す

撮り直しの扱いは、設定の `orders.retake_mode` で選びます。モダリティの側の撮り直しの
設定と合わせてください。

- `append`（既定）：同じ予約の中で撮り直します（IHE の Append Case）。RIS は何もしません
- `new_order`：撮り直しは別の検査です。予約の詳細の「撮り直しの予約を作る」か、
  次のコマンドで、新しい受付番号・Study Instance UID の撮り直しの予約を作ります

```bash
docker exec ris-emulator python -m app.cli retake RE202610210001
```

撮り直しを作れるのは、実施中・完了・中止の予約です。実施中の予約から作ると、元の予約は
中止になります（[spec/01_orders.md](spec/01_orders.md) の 7 章）。

## 7. HL7 のメッセージを送る

PACS の PIR（Patient Information Reconciliation）への対応を試すために、HL7 v2.3.1 の
メッセージを MLLP で送れます。送り先は設定の `hl7.host`・`hl7.port` です。
先に `--dry-run` で、組み立てたメッセージを確認できます。

```bash
# 仮の患者ID ER0001 を、正式な患者ID RE0000001 に統合する（ADT^A40）
docker exec ris-emulator python -m app.cli pir send --kind a40 \
  --patient-id RE0000001 --prior-patient-id ER0001 --name "YAMADA^TARO=山田^太郎=ヤマダ^タロウ"

# 保存済みの予約を知らせる（ORM^O01、ORC-1 は NW）
docker exec ris-emulator python -m app.cli pir send --kind orm --accession RE202610210001
```

PACS が受理すると終了コード 0、AE・AR で断ると 5、通信できないと 6 になります。
メッセージの中身と例は [spec/06_hl7_pir.md](spec/06_hl7_pir.md) にあります。
Docker から同じマシンの受け口へ送るときは、`hl7.host` にそのマシンのホスト名か
IP アドレスを書きます（`127.0.0.1` はコンテナ自身です）。

## 8. 予約の無い撮影を照合する

モダリティが予約なしで撮影すると（緊急の飛び込みなど）、仮の患者ID と氏名の撮影が
MPPS として記録されます。画面の「未照合」（`/reconciliation`）に出るので、「照合」で
正式な患者（名簿から選ぶか、入力）と検査名、依頼科を決めます。「照合・送信」で、
撮影の Study Instance UID を持つ新しい予約を作り、PACS へ HL7 を送ります。患者ID が
変わるときは ADT^A40 と ORM^O01、氏名などだけが変わるときは ADT^A08 と ORM^O01 です。

結果は予約の詳細の「HL7 送信」に残ります。PACS が断ったり、つながらなかったりしても
照合は取り消されません。原因を直したら、「再送信」で受理されていない通を同じ本文で
送り直します。

CLI でも同じことができます。

```bash
# 未照合の撮影（SOP Instance UID を見る）
docker exec ris-emulator python -m app.cli reconcile list

# 名簿の患者 P000001 で照合する。検査名と依頼科は省略できる
docker exec ris-emulator python -m app.cli reconcile run 1.2.826.0.1.3680043.8.498.1 \
  --roster-patient-id P000001

# 名簿に無い患者を入力して照合する
docker exec ris-emulator python -m app.cli reconcile run 1.2.826.0.1.3680043.8.498.1 \
  --patient-id RE0000001 --name "YAMADA^TARO=山田^太郎=ヤマダ^タロウ" \
  --birth-date 19800101 --sex M

# 受理されていない HL7 を送り直す
docker exec ris-emulator python -m app.cli reconcile resend RE202610210001
```

HL7 がすべて受理されれば終了コード 0、断られると 5、通信できないと 6 になります。
中身と規則は [spec/07_reconciliation.md](spec/07_reconciliation.md) にあります。

照合の後に、モダリティが同じ Study を仮の患者のまま撮ると、その MPPS は照合で作った
予約に結び付き、未照合の一覧には出ません。照合で作った予約を取消・中止にすると、
PACS へ ORM^O01（ORC-1 が CA・DC）を送り、予約の詳細の「HL7 送信」に行が足されます。

```bash
# 照合で作った予約を取消にして、PACS へ ORM（CA）を送る
docker exec ris-emulator python -m app.cli status RE202610210001 cancelled
```
