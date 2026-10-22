# Proposal

## Why

予約の画面の文字コードの選択肢は、Specific Character Set (0008,0005) の値を `\` で
つないだ文字列（`ISO_IR 192`・`\ISO 2022 IR 87`・`ISO 2022 IR 13\ISO 2022 IR 87`）を
そのまま出している。先頭の `\` は値の区切りで、1つ目の値が空（既定の文字の集合
ISO 2022 IR 6）であることを表し、値としては正しい（PS3.5 6.4、PS3.3 C.12.1.1.2）。
しかし日本語のフォントでは `¥` に見え、不要な記号に見える。何の文字コードかも
値の名前からは分かりにくい。値は変えずに、選択肢の表示を人が分かる名前にする。

## What Changes

- 文字コードの3つの選択肢に、表示の名前を付ける
  - `utf8`：「Unicode（UTF-8、ISO_IR 192）」
  - `jis`：「日本語（JIS X 0208、ISO 2022 IR 87）」
  - `jis_kana`：「日本語と半角カナ（JIS X 0201・JIS X 0208、ISO 2022 IR 13・ISO 2022 IR 87）」
- 予約の画面の選択肢、予約の詳細の「文字コード」、文字コードで書けない文字のエラーの文、
  CLI の `--charset` の説明に、この名前を使う。どこにも `\` でつないだ値を出さない
- MWL の応答の Specific Character Set の値は変えない。予約の詳細の「MWL の属性」の表示も、
  値をそのまま出す
- 3つの値が PS3.3 C.12.1.1.2 と PS3.5 6.1 の規則に合うことを、spec の要件と試験で固定する

## Capabilities

### New Capabilities

- `character-sets`: 予約ごとに選ぶ文字コードの選択肢、その Specific Character Set の値、
  画面と CLI での表示の名前

### Modified Capabilities

（なし。`openspec/specs/` にはまだ spec が無い）

## Impact

- コード：`app/core/models.py`（表示の名前の表）、`app/web/app.py`（`CHARACTER_SET_LABELS`）、
  `app/services/order_service.py`（`check_encodable` のエラーの文）、`app/cli/main.py`
- テスト：画面の選択肢とエラーの文の試験を足す。Specific Character Set の値の今の試験
  （`tests/core/test_mwl_dataset.py`・`tests/mwl/test_server.py`）はそのまま通る
- ドキュメント：`docs/spec/02_mwl_scp.md` の 5 章の表に表示の名前の列を足す
- MWL の応答・データベース・設定の値（`utf8`・`jis`・`jis_kana`）は変わらない
