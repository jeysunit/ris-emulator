# Tasks

## 1. 題とナビの言葉

- [x] 1.1 `base.html`・`orders.html`・`order_detail.html`・`new_order.html` の題・見出し・ナビ・リンクを「予約一覧」「予約作成」「予約一覧へ」にし、どの画面の HTML にも「予約の一覧」「予約を作る」が無いことを `tests/web/` で確かめる

## 2. 期間・本日・前日と翌日・頁送り

- [x] 2.1 `OrderStore.list_orders` に `limit`・`offset` を、`OrderStore` に同じ条件の件数を数えるメソッドを足し、範囲・件数・並びを `tests/services/` で確かめる
- [x] 2.2 `/orders` に `date_from`・`date_to`・`page` を足し、`date` を `date_from` として受け、`date=all`・逆順・31日を超える期間を 400 にすることを `tests/web/` で確かめる
- [x] 2.3 「本日」「前日」「翌日」のリンクと、頁の範囲の表示・前後の頁のリンクを `orders.html` に置き、絞り込みが保たれることと「全日付」が無いことを `tests/web/` で確かめる

## 3. 状態の列と画面の枠

- [x] 3.1 状態の列の `th`・`td` に `col-status` を付け、`app.css` で幅を固定し、`select` を列の幅いっぱいにする。すべての状態の行で状態の列に `col-status` が付くことを `tests/web/` で確かめる
- [x] 3.2 予定と完了が並ぶ一覧と完了だけの一覧で、状態の列の幅が同じになることを Playwright（127.0.0.1 の開発の環境）で測って確かめる
- [x] 3.3 フッターを削り、ヘッダーの製品名の横に版を出し、どの画面の HTML にも「開発・試験用」の帯が無いことを `tests/web/` で確かめる

## 4. ドキュメントと全体の確かめ

- [x] 4.1 `docs/spec/03_web_cli.md` の 3.1 の表と 3.2 の画面の文言を直し、markdownlint が合格することを確かめる
- [x] 4.2 `python -m pytest -q` がすべて合格することを確かめる

## Workflow follow-up

- PR のレビューの後に、この change を archive する
