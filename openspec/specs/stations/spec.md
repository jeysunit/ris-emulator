# stations Specification

## Purpose

予約の予定の装置を、運用上の名前で選べるようにする。装置の台帳を設定ファイルに持ち、
選んだ装置の AE タイトル・装置名・モダリティを MWL の Scheduled Procedure Step に入れる。

## Requirements

### Requirement: 装置の台帳は設定ファイルに持つ

設定の `orders.modalities.<モダリティ>.stations` に、1つ以上の装置を並べなければならない
（SHALL）。装置ごとに `name`（画面に出す名前）・`ae_title`・`station_name` を持つ。
装置のモダリティは、並べたモダリティのキーで決まる。

#### Scenario: 台帳を読み込む

- **WHEN** 設定の CT に `{name: "CT1号機", ae_title: "CT01", station_name: "CT01"}` と `{name: "CT2号機", ae_title: "CT02", station_name: "CT02"}` を並べて起動する
- **THEN** 予約の画面の CT の装置の選択肢に「CT1号機」と「CT2号機」が出る

### Requirement: 台帳の値は DICOM の規則で検証する

設定を読み込むときに、`ae_title` を PS3.5 6.2 の AE の規則（16 文字まで、表示できる ASCII で
`\` を含まない、空白だけにしない）で、`station_name` を SH の規則（16 文字まで、`\` と
制御文字を含まない）で検証しなければならない（SHALL）。`name` は空にせず、前後に空白を
付けず、64 文字までとし、台帳の全体で重ねない。誤りがあれば、キーの位置を示して起動しない。

#### Scenario: AE タイトルが長すぎる

- **WHEN** 台帳の `ae_title` に 17 文字の値を書いて起動する
- **THEN** 設定のエラーになり、`orders.modalities.CT.stations.0.ae_title` の位置が示され、終了コードは 2 になる

#### Scenario: 名前が重なる

- **WHEN** CT と MR の台帳に、同じ `name` の装置を書いて起動する
- **THEN** 設定のエラーになり、重なった名前が示される

### Requirement: 古い形の設定は読み込まない

設定に `station_ae_titles` か `station_name`（モダリティの直下）があれば、`stations` の形を
示す設定のエラーにしなければならない（SHALL）。古い値を推測して変換しない。

#### Scenario: 古い設定で起動する

- **WHEN** `orders.modalities.CT.station_ae_titles: ["CT01"]` のある設定で起動する
- **THEN** 設定のエラーになり、`stations` に書き換えるよう示される

### Requirement: 予約の画面ではモダリティごとに装置を選ぶ

予約作成の画面は、選んだモダリティの台帳の装置から1台を選ぶ欄を出さなければならない
（SHALL）。既定は台帳の1台目とする。

一括作成の画面は、件数を入れるモダリティのうち、台帳に装置が2台以上あるものだけに、
台帳の装置と「全装置に振り分け」（既定）の選択肢を出す。「全装置に振り分け」のときは、
台帳の装置を予約ごとに並べた順に使う。台帳に装置が1台だけのモダリティは、その装置で作る。

どちらの画面も、AE タイトルを文字で入れる欄は出さない。「順に使う」の言葉は出さない。

#### Scenario: 装置を選んで予約を作る

- **WHEN** CT の台帳に CT1号機・CT2号機があり、利用者が一括作成で CT を 2 件、装置に「CT2号機」を選んで作る
- **THEN** 2 件とも Scheduled Station AE Title は `CT02`、Scheduled Station Name は `CT02` になる

#### Scenario: 装置を選ばずに予約を作る

- **WHEN** CT の台帳に CT1号機・CT2号機があり、利用者が一括作成で装置を既定の「全装置に振り分け」のままにして CT を 3 件作る
- **THEN** 予約の Scheduled Station AE Title は順に `CT01`・`CT02`・`CT01` になる

#### Scenario: 台帳に装置が1台のモダリティ

- **WHEN** CT の台帳に装置が1台だけのときに一括作成の画面を開く
- **THEN** CT の欄に装置の選択肢は出ず、CT の予約はその装置で作られる

#### Scenario: 予約作成の装置の既定

- **WHEN** CT の台帳に CT1号機・CT2号機があり、利用者が予約作成の画面でモダリティを CT にする
- **THEN** 装置の選択肢は CT1号機・CT2号機で、CT1号機が選ばれている

#### Scenario: 別のモダリティの装置が送られる

- **WHEN** 画面の CT の装置の欄に、MR の台帳にある装置の名前が送られる
- **THEN** 応答は 400 になり、予約は作られない

### Requirement: CLI では装置の名前で選ぶ

CLI の `create` は、`--station <装置の名前>` で装置を選べなければならない（SHALL）。
モダリティごとに1つまで、繰り返して指定できる。台帳に無い名前、件数を指定していない
モダリティの装置、同じモダリティの2つ目の指定は、入力のエラー（終了コード 2）にする。

#### Scenario: 2つのモダリティの装置を選ぶ

- **WHEN** 利用者が `create CT=1 MR=1 --station CT2号機 --station MR1号機` を実行する
- **THEN** CT の予約は `CT02`、MR の予約は MR1号機の AE タイトルになり、終了コードは 0 になる

#### Scenario: 台帳に無い名前

- **WHEN** 利用者が `create CT=1 --station CT9号機` を実行する
- **THEN** 予約は作られず、終了コードは 2 になり、CT の台帳の名前が示される

### Requirement: 装置の属性を MWL に入れる

予約の MWL の Scheduled Procedure Step Sequence (0040,0100) の項目には、選んだ装置の
`ae_title` を Scheduled Station AE Title (0040,0001)、`station_name` を Scheduled Station
Name (0040,0010)、台帳のモダリティを Modality (0008,0060) に入れなければならない（SHALL。
PS3.4 Table K.6-1）。`station_name` が空なら、Scheduled Station Name は空の値で返す
（Return Key Type 2）。

#### Scenario: モダリティが自分の AE タイトルで絞り込む

- **WHEN** CT2号機の予約を作り、モダリティが Scheduled Station AE Title `CT02` で C-FIND を送る
- **THEN** その予約が返り、Modality は `CT`、Scheduled Station Name は `CT02` になる

### Requirement: 装置の名前を予約に残して表示する

予約に装置の `name` を保存し、予約の一覧と詳細に表示しなければならない（SHALL）。
装置の名前は MWL の属性には入れない。名前を持たない保存済みの予約は、AE タイトルを表示する。

#### Scenario: 一覧に装置の名前が出る

- **WHEN** 利用者が CT1号機の予約の一覧を開く
- **THEN** 装置の列に「CT1号機」と表示される
