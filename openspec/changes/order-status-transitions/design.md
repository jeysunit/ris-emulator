# Design

## Context

- `OrderStore.set_status`（`app/services/store.py`）は、`BEGIN IMMEDIATE` の中で予約を
  読み、状態を書き換える。今の状態は見ていない
- 画面の一覧の行（`_order_row.html`）は htmx で状態を POST し、応答の行で置き換える。
  htmx の設定（`base.html`）は 4xx の応答では行を置き換えない
- CLI の `status` は argparse の `choices` で4つの値だけを受け、`ValidationError` を
  終了コード 2 にする

## Goals / Non-Goals

**Goals:**

- 遷移の表を1か所（`app/core/models.py`）に置き、ストア・画面・CLI がそれを使う
- 許さない遷移は、ストアの層で必ず止める（画面の選択肢を絞るだけにしない）

**Non-Goals:**

- 状態の変更の履歴（誰がいつ変えたか）の記録
- 「中止」の状態（`mpps-scp` で足す）

## Decisions

### 遷移の表は辞書で持つ

`ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]]` を `models.py` に置き、
`can_transition(current, new)` で引く。同じ状態は表に入れず、関数の側で「何もしない」に
分ける。代案の「終わりの状態の集合だけを持つ」は、`mpps-scp` で中止を足すときに
「中止へは実施中からだけ」のような向きの制限を書けないので選ばない。

### 検証はストアのトランザクションの中で行う

`set_status` の `BEGIN IMMEDIATE` の中で今の状態を読み、表に無ければ `ROLLBACK` して
新しい例外 `InvalidTransitionError`（`ValidationError` の子）を投げる。サービスの層で
読んでから書くと、画面と CLI が同時に変更したときに検証が破れる。`ValidationError` の子に
するので、CLI は今の処理のまま終了コード 2 になる。

### 画面は 400 を返し、行を置き換えない

一覧の行の htmx の POST が断られたときは 400 を返す。htmx は 4xx で行を置き換えないので、
選択肢は送る前の値に見えたまま残る。これを避けるため、行の `<select>` には今の状態から
変更できる状態だけを出し（spec の「画面は変更できる状態だけを選ばせる」）、断られるのは
同時の変更が重なったときだけにする。詳細の画面は、フォームの POST が断られたら、
エラーの文を付けて詳細を表示し直す。

## Risks / Trade-offs

- [完了・取消の誤操作を戻せない] → 試験の環境のツールなので、新しい予約を作ってやり直す。
  戻す操作を足すなら、別の change で「やり直し」として新しい Study Instance UID を発番する形にする
- [htmx の 400 で選択肢の表示が実際の状態とずれる] → 断られたら一覧を読み直すよう
  エラーの文に書く。重なるのは同時の変更のときだけ

## Migration Plan

保存の形は変えない。今のデータベースにある完了・取消の予約は、そのまま終わりの状態として
扱う。戻すときは、この change の commit を revert する。
