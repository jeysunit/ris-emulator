# Proposal

## Why

予約の画面では、予定の AE タイトルを文字で直接入れる。利用者は装置を「CT1号機」の
ような運用上の名前で呼ぶので、AE タイトルを覚えて打つ必要があり、打ち間違えると
モダリティが自分の AE タイトルで絞り込んだときに予約が返らない。また、1回の作成で
入れた AE タイトルは CT にも MR にも同じ値が入る。装置の台帳を持ち、名前で選ぶと、
その装置の AE タイトル・装置名・モダリティが MWL に入るようにする。

## What Changes

- 設定ファイルに装置の台帳を持つ。`orders.modalities.<モダリティ>.stations` に、装置ごとの
  名前（画面の表示用）・AE タイトル・装置名を並べる
- **BREAKING** 設定の `orders.modalities.<モダリティ>.station_ae_titles` と `station_name` を
  廃止する。古いキーのある設定ファイルは、新しいキーを示すエラーで読み込まない
- 予約の画面の「予定の AE タイトル」の入力欄を、モダリティごとの装置の選択に替える。
  選ばなければ、今と同じく台帳の装置を予約ごとに順に使う
- **BREAKING** CLI の `create` の `--station-ae` を `--station <装置の名前>` に替える
  （モダリティごとに1つ、繰り返して指定できる）
- 選んだ装置の AE タイトルを Scheduled Station AE Title (0040,0001)、装置名を
  Scheduled Station Name (0040,0010)、台帳のモダリティを Modality (0008,0060) に入れる
- 予約に装置の名前を保存し、一覧と詳細に表示する

## Capabilities

### New Capabilities

- `stations`: 装置の台帳の持ち方と検証、予約での装置の選び方、MWL に入れる装置の属性

### Modified Capabilities

（なし。`openspec/specs/` にはまだ spec が無い）

## Impact

- コード：`app/services/config.py`（台帳の読み込みと検証）、`app/core/models.py`
  （予約に装置の名前を足す）、`app/services/order_service.py`、`app/cli/main.py`、
  `app/web/app.py`・`new_order.html`・`_order_row.html`・`order_detail.html`
- 設定：`config/app_config.yaml` の6つのモダリティを新しい形に書き換える
- テスト：予定の AE タイトルの試験（`tests/services/test_order_service.py`・
  `tests/web/test_web.py`）は、装置の選択の試験に書き換える（削除しない）
- ドキュメント：`docs/spec/01_orders.md` の 1 章、`docs/spec/03_web_cli.md` の 2〜4 章、
  `docs/usage.md`、`docs/project_charter.md` の範囲
- データ：保存済みの予約は装置の名前を持たない。表示では AE タイトルで代える
- 利用者：自分の設定ファイルを使う人は、`stations` の形に書き換える
