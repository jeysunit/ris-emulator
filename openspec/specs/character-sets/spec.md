# character-sets Specification

## Purpose

予約ごとに選ぶ応答の文字コードの選択肢と、その Specific Character Set (0008,0005) の値、
画面と CLI で人に見せる名前を定める。

## Requirements

### Requirement: 選択肢と Specific Character Set の値

文字コードの選択肢は3つで、MWL の応答の Specific Character Set (0008,0005) に次の値を
入れなければならない（SHALL）。

| 選択肢 | 値 1 | 値 2 |
|--------|------|------|
| `utf8` | `ISO_IR 192` | なし |
| `jis` | 空（ISO 2022 IR 6） | `ISO 2022 IR 87` |
| `jis_kana` | `ISO 2022 IR 13` | `ISO 2022 IR 87` |

#### Scenario: jis の予約を MWL で返す

- **WHEN** 文字コードを `jis` にした予約に一致する C-FIND を送る
- **THEN** 応答の Specific Character Set は、1つ目が空、2つ目が `ISO 2022 IR 87` の2つの値になる

### Requirement: 値は PS3.3 C.12.1.1.2 の規則に合う

Specific Character Set の値は、PS3.3 C.12.1.1.2 の規則に合わなければならない（SHALL）。
`ISO_IR 192` は符号拡張を使わない文字の集合なので、値は1つだけにする。符号拡張を使う
値（`ISO 2022` で始まる語）は2つ以上の値で書き、同じ文字の集合を2回使わない。値 1 を
空にしたときは ISO 2022 IR 6 とみなされる。`ISO 2022 IR 13` は Table C.12-3、
`ISO 2022 IR 87` は Table C.12-4 の Defined Terms。`jis` と `jis_kana` は PS3.5 H.3.1・H.3.2 の
例と同じ値。

#### Scenario: 3つの選択肢の値を確かめる

- **WHEN** 3つの選択肢のそれぞれで予約を作り、MWL の応答の Specific Character Set を読む
- **THEN** `ISO_IR 192` は1つだけの値で、`ISO 2022` で始まる語を含む値は2つの値になり、どの値も重ならない

### Requirement: 符号化は PS3.5 6.1.2.5 に従う

符号拡張を使う選択肢（`jis`・`jis_kana`）の文字列の値は、値の始め、`^`・`=` の区切りの前、
値の終わりで、値 1 の文字の集合（`jis` では ISO 2022 IR 6）に戻さなければならない
（SHALL。PS3.5 6.1.2.5.3）。エスケープシーケンスは PS3.3 の Table C.12-3・C.12-4 にあるものだけを使う。

#### Scenario: PS3.5 H.3.1 の例と同じバイト列になる

- **WHEN** 文字コードを `jis` にして、氏名 `Yamada^Tarou=山田^太郎=やまだ^たろう` の予約の Patient's Name を符号化する
- **THEN** バイト列は PS3.5 Example H.3-1 の Encoded representation と同じになる

### Requirement: 画面と CLI は表示の名前で見せる

予約の画面の選択肢、予約の詳細の「文字コード」、文字コードで書けない文字のエラーの文、
CLI の `--charset` の説明は、次の表示の名前を使わなければならない（SHALL）。
Specific Character Set の値を `\` でつないだ文字列は出さない。

| 選択肢 | 表示の名前 |
|--------|------------|
| `utf8` | Unicode（UTF-8、ISO_IR 192） |
| `jis` | 日本語（JIS X 0208、ISO 2022 IR 87） |
| `jis_kana` | 日本語と半角カナ（JIS X 0201・JIS X 0208、ISO 2022 IR 13・ISO 2022 IR 87） |

#### Scenario: 予約の画面の選択肢

- **WHEN** 利用者が予約の画面を開く
- **THEN** 文字コードの選択肢は表示の名前の3つで、どの選択肢にも `\` と `¥` は含まれない

#### Scenario: 書けない文字のエラー

- **WHEN** 利用者が、文字コードを `jis` にして、名簿の氏名に `髙` を含む患者で予約を作る
- **THEN** 予約は作られず、エラーの文に「日本語（JIS X 0208、ISO 2022 IR 87）」と書かれる

### Requirement: MWL の属性の表示は値をそのまま出す

予約の詳細の「MWL の属性」は、Specific Character Set の値を変えずに出さなければならない
（SHALL）。表示の名前に置き換えない。

#### Scenario: 詳細で値を確かめる

- **WHEN** 利用者が、文字コードを `jis` にした予約の詳細を開く
- **THEN** 「文字コード」には表示の名前が、「MWL の属性」の Specific Character Set には空の値と `ISO 2022 IR 87` の2つの値が出る
