# ADR-0009: 装置の台帳は設定ファイルに持ち、予約では装置を名前で選ぶ

- 状態：採用
- 作成日：2026-10-23
- 最終更新日：2026-10-23

## 背景

予約の画面では、予定の AE タイトルを文字で直接入れていた。利用者は装置を「CT1号機」の
ような運用上の名前で呼ぶので、AE タイトルを覚えて打つ必要があり、打ち間違えるとモダリティが
自分の AE タイトルで絞り込んだときに予約が返らない。1回の作成で入れた AE タイトルは、
件数を入れたすべてのモダリティに同じ値が入っていた。設定の `station_ae_titles`（AE タイトルの
並び）と `station_name`（モダリティに1つ）は別々に持っていたので、AE タイトルと装置名の組も
ずれうる。

## 決定

1. **装置の台帳を設定ファイルに持つ。** `orders.modalities.<モダリティ>.stations` に、装置ごとの
   `name`（運用上の名前）・`ae_title`（Scheduled Station AE Title (0040,0001)）・
   `station_name`（Scheduled Station Name (0040,0010)）を並べる。理由：設定は YAML で持ち、
   画面は予約だけを扱うという今の作りに合う。試験の環境では装置の構成は頻繁に変わらない
2. 台帳はモダリティの下に置き、装置に `modality` の欄を持たない。欄で持つと、台帳のモダリティと
   検査の種類のモダリティが食い違う設定が書けてしまう
3. 予約の画面と CLI では、モダリティごとに装置を名前で選ぶ。選ばなければ台帳の装置を予約ごとに
   順に使う。AE タイトルを文字で入れる欄と `--station-ae` は無くす
4. 古い形のキー（`station_ae_titles`・`station_name`）は変換せずにエラーにする。変換すると名前を
   推測で決めること（AE タイトルを名前にする）になり、画面に出る名前が利用者の意図と違ってしまう
5. 予約に装置の名前（`scheduled_station_label`）を残し、一覧と詳細に出す。MWL の属性には入れない

## 検討した選択肢

| 案 | 持ち方 | 採らなかった理由 |
|----|--------|------------------|
| データベースの表と画面の編集 | 再起動なしで台帳を変えられる | 表・編集の画面・CSRF・削除した装置を参照する予約の扱いが要り、試験の範囲が広がる。要るときは、設定の台帳を初期値として表に移す形で後から足せる |
| 古いキーを変換する | 利用者の設定を書き換えずに済む | 上の決定 4 の理由 |

## 結果

- 予約の画面で装置を名前で選べ、その装置の AE タイトル・装置名・モダリティの組がずれない
- 自分の設定ファイルを使う利用者は、`stations` の形に書き換える必要がある
  （ルートの README の「バージョンアップの時の注意」）
- 台帳を変えるには、設定ファイルを直して再起動する

## 出典（2026-10-23 に確認）

- DICOM PS3.4 Table K.6-1（Scheduled Station AE Title は Matching Key Type R・Return Key
  Type 1、Scheduled Station Name は Matching Key Type O・Return Key Type 2）
  <https://dicom.nema.org/medical/dicom/current/output/chtml/part04/sect_K.6.html>
- DICOM PS3.5 6.2 Value Representation（AE・SH）
  <https://dicom.nema.org/medical/dicom/current/output/chtml/part05/sect_6.2.html>

## 関連

- [spec/01_orders.md](../spec/01_orders.md) の 1 章、[spec/03_web_cli.md](../spec/03_web_cli.md)
  の 4 章
