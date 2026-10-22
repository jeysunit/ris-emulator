# Proposal

## Why

画面と文書で、DICOM の属性に付けている日本語の名前を一覧にして見直す。Requesting
Physician (0032,1032) は日本の RIS では「依頼医」、Referring Physician's Name (0008,0090) は
「紹介医」と呼ぶのが普通で、2つを取り違えると、モダリティや PACS の画面と RIS の画面で
同じ医師が別の名前で呼ばれる。

調べた結果（2026-10-23、main と公開のすべてのブランチ）、画面・CLI・文書のどこにも
「紹介医」は無く、(0032,1032) を「紹介医」と呼んでいる箇所も無い。誤りは1つで、
`docs/spec/01_orders.md` の 1 章の表が、(0032,1032) と (0008,0090) の2つを1行の「依頼医」に
まとめている。

## What Changes

- 画面と文書で DICOM の属性に付ける日本語の名前を、用語の表として spec に定める
- `docs/spec/01_orders.md` の 1 章の表の「依頼医」の行を、「依頼医：Requesting Physician
  (0032,1032)」と「紹介医：Referring Physician's Name (0008,0090)」の2行に分ける。値の決め方
  （乱数の同じ氏名）は変えない
- 画面の文言は変えない。今の名前はすべて表のとおり（design.md の一覧）
- `docs/spec/03_web_cli.md` の 3.2「画面の文言」から、用語の表を参照する

## Capabilities

### New Capabilities

- `screen-terms`: 画面と文書で DICOM の属性に付ける日本語の名前

### Modified Capabilities

（なし。`openspec/specs/` にはまだ spec が無い）

## Impact

- コード：変えない。用語の表のとおりであることを確かめる試験を `tests/web/test_web.py` に足す
- ドキュメント：`docs/spec/01_orders.md` の 1 章の表、`docs/spec/03_web_cli.md` の 3.2
- `station-registry`・`character-set-labels` で足す画面の名前（装置・文字コードの名前）は、
  それぞれの change で用語の表に足す
