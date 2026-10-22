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

Web 画面（<http://127.0.0.1:8081/>、ユーザー名 `ris`）と MWL（AE タイトル `RIS_EMU`、
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

モダリティが自分の AE タイトルで絞り込んで問い合わせる場合は、設定の
`orders.modalities.<モダリティ>.station_ae_titles` をモダリティの AE タイトルに
変更します（既定値と規則は [spec/03_web_cli.md](spec/03_web_cli.md) の 4 章）。

## 4. 予約を作成する

CLI をコンテナの中で実行して作成します。Web 画面の `/orders/new` からも作成できます。

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
