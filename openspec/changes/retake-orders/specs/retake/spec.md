# Spec Delta

## Purpose

撮影のやり直しを、同じ検査の中のシリーズの追加として扱うか、新しい検査として扱うかを
設定で選べるようにし、新しい検査として扱うときの撮り直しの予約の作り方を定める。

## ADDED Requirements

### Requirement: 撮り直しの扱いは設定で選ぶ

設定の `orders.retake_policy` は、`same_study` と `new_order` のどちらかでなければならない
（SHALL）。既定は `same_study`。ほかの値の設定は読み込まない。

#### Scenario: 設定を書かずに起動する

- **WHEN** `orders.retake_policy` を書かない設定で起動する
- **THEN** 撮り直しの扱いは `same_study` になり、予約の詳細に撮り直しのボタンは出ない

#### Scenario: 知らない値

- **WHEN** `orders.retake_policy: copy` の設定で起動する
- **THEN** 設定のエラーになり、`same_study` と `new_order` が示される

### Requirement: same_study では撮り直しの予約を作らない

`same_study` のとき、撮り直しは同じ予約・同じ Study Instance UID の中のシリーズの追加として
扱い（IHE RAD の Scheduled Workflow）、RIS は撮り直しの予約を作ってはならない（SHALL NOT）。
CLI の `retake` は入力のエラー（終了コード 2）にし、画面は撮り直しのボタンを出さない。

#### Scenario: same_study で CLI の retake を使う

- **WHEN** `same_study` の設定で、利用者が `retake <受付番号>` を実行する
- **THEN** 予約は作られず、終了コードは 2 になり、設定が `same_study` であることが示される

#### Scenario: 完了の予約に追加のシリーズの MPPS が来る

- **WHEN** `same_study` の設定で、完了の予約に結び付く新しい MPPS の N-CREATE と N-SET（COMPLETED）が届く
- **THEN** どちらも 0000H になり、予約は完了のまま、予約の数も変わらない

### Requirement: new_order では撮り直しの予約を作る

`new_order` のとき、実施中・完了・中止の予約から、撮り直しの予約を作れなければならない
（SHALL）。作るのは予約の詳細の画面と CLI の `retake <受付番号> [--date] [--start]`。
予定と取消の予約からは作らない（入力のエラー）。

#### Scenario: 完了の予約から撮り直しを作る

- **WHEN** `new_order` の設定で、利用者が完了の予約の詳細で「撮り直し」を押す
- **THEN** 状態が予定の新しい予約が1件でき、その詳細の画面に移る

#### Scenario: 予定の予約から撮り直しを作ろうとする

- **WHEN** `new_order` の設定で、利用者が予定の予約に `retake <受付番号>` を実行する
- **THEN** 予約は作られず、終了コードは 2 になる

### Requirement: 撮り直しの予約は内容を写し、番号を新しく発番する

撮り直しの予約は、元の予約の患者・モダリティ・装置・検査・依頼科・依頼医・紹介医・施設名・
優先度・文字コードを写し、受付番号・Requested Procedure ID・Scheduled Procedure Step ID・
Study Instance UID を、新しい予約と同じ規則（`docs/spec/04_identifiers.md`）で発番しなければ
ならない（SHALL）。予定日時は、指定が無ければ作った時点の日付と時刻（分まで）にする。

#### Scenario: 番号がすべて変わる

- **WHEN** `new_order` の設定で、受付番号 `RE202610230001` の予約から撮り直しを作る
- **THEN** 新しい予約の受付番号・Requested Procedure ID・Scheduled Procedure Step ID・Study Instance UID はどれも元と違い、患者 ID と検査名は元と同じになる

#### Scenario: MWL で撮り直しの予約を取得する

- **WHEN** 撮り直しの予約を作った後に、モダリティが自分の AE タイトルと今日の日付で C-FIND を送る
- **THEN** 撮り直しの予約が新しい Study Instance UID で返る

### Requirement: 元の予約の状態を合わせる

撮り直しの予約を作るときは、元の予約が実施中なら中止にし、完了・中止ならそのままに
しなければならない（SHALL）。撮り直しの予約の作成と元の予約の状態の変更は、1つの
トランザクションで行う。

#### Scenario: 実施中の予約から撮り直しを作る

- **WHEN** `new_order` の設定で、実施中の予約から撮り直しを作る
- **THEN** 元の予約は中止になり、MWL で返らなくなる

#### Scenario: 完了の予約から撮り直しを作る

- **WHEN** `new_order` の設定で、完了の予約から撮り直しを作る
- **THEN** 元の予約は完了のままになる

### Requirement: 元の予約との関係を残す

撮り直しの予約には元の受付番号を保存し、予約の詳細には、元の予約と、その予約から作った
撮り直しの予約の受付番号を、互いにリンクで表示しなければならない（SHALL）。撮り直しの
予約から、さらに撮り直しを作ってもよい。この関係は MWL の属性には入れない。

#### Scenario: 詳細で関係をたどる

- **WHEN** 予約 X から撮り直しの予約 Y を作り、利用者が Y の詳細を開く
- **THEN** 「撮り直しの元」に X の受付番号がリンクで出て、X の詳細には「撮り直し」に Y の受付番号が出る
