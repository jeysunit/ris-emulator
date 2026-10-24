# Proposal

## Why

3 製品の画面の型（tsunagi-dicom の `docs/design-system` の画面の型 B）に合わせる。
予約を探す一覧を 6 列に絞り、補足と状態の変更を右の区画へ移して、予定の把握と操作をしやすくする。

## What Changes

- 共通の上の帯と左のナビ、色・文字・余白を整える
- 予約の一覧を検索の帯、状態の要約、一覧と選んだ予約の区画にする
- 患者ID・受付番号の完全一致検索と状態別の集計を追加する
- 状態の変更の成功時は画面全体を読み直し、失敗時は選択を保存済みの状態へ戻す

## Capabilities

### New Capabilities

なし。

### Modified Capabilities

- `order-list`: 枠、題、検索、要約、選択区画、ページ送り、状態変更
- `screen-terms`: 一覧の 6 列の見出し
- `order-status`: 状態の選択欄の場所
- `stations`: 装置名の表示場所
- `order-entry`: ナビと一覧へのリンクの語

## Impact

Web、予約の保存・サービス、試験、利用手順と仕様書を更新する。
データベースの構造、CLI、MWL の応答は変えない。
