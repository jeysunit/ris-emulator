# Design

## Context

- 選択肢と値の対応は `app/core/models.py` の `CHARACTER_SET_TERMS` にあり、画面の表示
  （`app/web/app.py` の `CHARACTER_SET_LABELS`）とエラーの文（`check_encodable`）は、
  その値を `\` でつないで作っている
- 3つの値の規格との照合は、2026-10-23 に次の節で行った（DICOM 2026d）
  - PS3.5 6.4：文字列の複数の値は 5CH（`\`）で区切る。`\ISO 2022 IR 87` の先頭の `\` は区切り
  - PS3.3 C.12.1.1.2：値が2つ以上なら符号拡張を使う。値 1 が空なら ISO 2022 IR 6。
    同じ文字の集合を2回使わない。`ISO_IR 192` は値 1 にだけ書き、値は1つだけ
  - PS3.3 Table C.12-3 に `ISO 2022 IR 13`（JIS X 0201 のカナ。G0 は ISO-IR 14 のローマ字）、
    Table C.12-4 に `ISO 2022 IR 87`（JIS X 0208）がある
  - PS3.5 H.3.1（`\ISO 2022 IR 87`）と H.3.2（`ISO 2022 IR 13\ISO 2022 IR 87`）の例と同じ値
  - 結果：3つとも規格に合う。値を変える必要は無い

## Goals / Non-Goals

**Goals:**

- 人に見せる場所では、選択肢を名前で見せる
- 値が規格に合うことを試験で固定する

**Non-Goals:**

- 選択肢を増やすこと（`ISO_IR 13` の1つの値だけ、JIS X 0212 の `ISO 2022 IR 159` など）
- 設定・CLI の選択肢の値（`utf8`・`jis`・`jis_kana`）を変えること

## Decisions

### 表示の名前は models.py に置く

`CHARACTER_SET_LABELS: dict[CharacterSet, str]` を `CHARACTER_SET_TERMS` の隣に置き、画面・
サービス・CLI はそれを使う。値と名前を同じ場所に置くと、選択肢を足すときに片方を忘れにくい。
`app/web/app.py` で値から作る今の `CHARACTER_SET_LABELS` は削除する。

### 名前は「言語（規格の名前、Defined Term）」の形にする

「日本語」だけでは、`jis` と `jis_kana` の違いが分からない。規格の名前（JIS X 0208 など）は
モダリティの設定の画面に出る名前に合わせ、Defined Term は DICOM の Conformance Statement と
照らすために残す。Defined Term の間は `\` でなく `・` でつなぐ。

### 「MWL の属性」は値をそのまま出す

詳細の画面の「MWL の属性」は、モダリティが受け取る値を確かめるための表示なので、
名前に置き換えない。pydicom の表示（`['', 'ISO 2022 IR 87']`）のままにする。

## Risks / Trade-offs

- [`jis_kana` の G0 は ISO-IR 14（JIS X 0201 のローマ字）で、05/12 は `¥`、07/14 は
  オーバーラインになる（PS3.5 6.1.2.5.3 の Note）] → 値の `\` は今も断っている。`~` を含む
  値は、受け取る側によって別の字に見える。この change では扱わず、要るなら `check_encodable` で
  `jis_kana` の `~` を断る change を別に作る
- [表示の名前が長く、選択肢の幅が広がる] → 画面の CSS で選択肢の幅を制限しない。
  画面の幅が狭いときは折り返す
