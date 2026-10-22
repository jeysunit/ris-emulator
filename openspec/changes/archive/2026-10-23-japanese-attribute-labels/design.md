# Design

## Context

2026-10-23 に、画面（`app/web/templates/`）・CLI（`app/cli/main.py`）・文書（`docs/`）の
DICOM の属性の日本語の名前を一覧にした。`git grep 紹介医` は main と公開のすべてのブランチで
何も返さない。

| 属性 | 今の名前 | 使う場所 | 見立て |
|------|----------|----------|--------|
| Accession Number (0008,0050) | 受付番号 | 一覧・詳細・CLI・文書 | 合う。病院によって「オーダ番号」とも呼ぶが、DICOM の訳としては受付番号が普通 |
| Patient ID (0010,0020) | 患者 ID | 一覧・詳細 | 合う |
| Patient's Name (0010,0010) | 患者氏名 | 一覧・詳細 | 合う |
| Patient's Birth Date・Sex | 生年月日・性別 | 一覧 | 合う |
| Modality (0008,0060) | モダリティ | 一覧・詳細・作成 | 合う |
| Requested Procedure Description (0032,1060) | 検査名 | 一覧・詳細・文書 | 合う。RIS によっては「検査項目」「撮影部位」 |
| Requesting Service (0032,1033) | 依頼科 | 一覧・詳細・作成・CLI | 合う |
| Requesting Physician (0032,1032) | 依頼医（文書だけ） | `01_orders.md` | 合う |
| Referring Physician's Name (0008,0090) | 依頼医（文書だけ、(0032,1032) と同じ行） | `01_orders.md` | **誤り**。紹介医と書く |
| Scheduled Station AE Title (0040,0001) | 予定の AE タイトル | 一覧・詳細・作成 | 合う |
| Scheduled Station Name (0040,0010) | 予定の装置名 | 文書 | 合う |
| Scheduled Procedure Step Start Date・Time | 予定日時 | 一覧・詳細 | 合う |
| Institution Name (0008,0080) | 施設名 | 文書 | 合う |
| Requested Procedure Priority (0040,1003) | 優先度 | 文書 | 合う |
| Specific Character Set (0008,0005) | 文字コード | 詳細・作成 | 合う |
| Scheduled Performing Physician's Name (0040,0006) | （名前なし） | なし | 表に「実施予定医」を置く |
| Requested Procedure ID・Scheduled Procedure Step ID・Study Instance UID | 英語のまま | 詳細 | 合う。Study Instance UID には「検査インスタンス UID」の訳もあるが、モダリティ・PACS の画面と照らしやすいように英語のままにする |

「見立て」は、日本の病院の RIS・PACS の画面で普通に使う言葉と、次の2つの日本語の
DICOM の用語の資料（2026-10-23 に参照）と照らしたものである。資料は訳語を決める参考に
使い、表は写していない。

- 標準DICOM画像タグセット一覧（リベルワークス）
  <https://www.liberworks.co.jp/know/know_dicomTag.html>
- DICOM用語集（SonicDICOM）<https://ja.sonicdicom.com/dicom-glossary/>

資料と違う名前にしたもの：

| 属性 | 資料の訳 | この RIS の名前 | 理由 |
|------|----------|-----------------|------|
| Referring Physician's Name (0008,0090) | 照会医師の名前（2つとも） | 紹介医 | 規格の英語を直訳した名前。日本の病院の RIS・PACS の画面では「紹介医」と呼ぶ |
| Patient's Name (0010,0010) | 患者の名前・患者氏名 | 患者氏名 | 画面で普通に使う方 |
| Patient's Birth Date (0010,0030) | 患者の誕生日・患者生年月日 | 生年月日 | 一覧では「患者」の列の中にあるので「患者」を付けない |
| Specific Character Set (0008,0005) | 特定文字集合 | 文字コード | 画面の利用者に通じる言葉。予約の画面の項目には英語の属性名を添えている |

Requesting Physician (0032,1032)・Requesting Service (0032,1033)・Requested Procedure
Description (0032,1060) と Scheduled Procedure Step の属性は、2つの資料に無い（画像の属性の
一覧のため）。

JJ1017 の指針（日本放射線技術学会の「HIS，RIS，PACS，モダリティ間予約，会計，照射録情報
連携指針」。JIRA ではなく JSRT の指針で、提案のときに「JIRA の文書」と書いたのは誤り）の
本文 Ver.3.4（2024）とも照らした（2026-10-23）。本文は手技・部位などのコードと HL7・DICOM
の使い方を定めるもので、上の表の属性の日本語の名前（依頼医・紹介医・受付番号・検査名など）は
定めていない。このため、指針との違いは無く、名前は変えない。

- JJ1017 指針 Ver.3.4（2024）本文
  <https://www.jsrt.or.jp/97mi/content/jj1017/v3_4_2024/jj1017_v3_4_2024_guideline.pdf>

一覧の作成の後に、装置の台帳（change `station-registry`）で、予約の一覧の列は「装置」
（台帳の名前と AE タイトル）になり、詳細には「装置」「予定の AE タイトル」「予定の装置名」が
並ぶ。「装置」は DICOM の属性の訳ではないので、用語の表には入れない。

## Goals / Non-Goals

**Goals:**

- 用語の表を spec に置き、新しい画面の文言を足すときの基準にする
- 明らかな誤り（(0008,0090) を依頼医と呼んでいる行）を直す

**Non-Goals:**

- 画面に依頼医・紹介医を出すこと（今は MWL の属性の表示にだけある）
- 依頼医と紹介医に別の人を入れること。日本の RIS では、院内の依頼医を Referring Physician's
  Name にも入れることが多いので、同じ氏名のままにする

## Decisions

### 用語の表は spec に置き、コードには置かない

名前はテンプレートに直に書いてあり、選択肢のように値と対応させる必要が無い。表を
コードに置くと、テンプレートを読むときに表を引く手間が増える。試験で見出しが表の名前と
一致することを確かめる。

## Risks / Trade-offs

- [病院によって呼び方が違う（受付番号とオーダ番号など）] → 表は DICOM の属性の訳として
  普通のものにする。画面の名前を設定で変える機能は作らない
