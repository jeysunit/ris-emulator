# screen-terms Specification

## Purpose

画面と文書で DICOM の属性に付ける日本語の名前を1つに決め、RIS・モダリティ・PACS の
画面と同じ言葉で読めるようにする。

## Requirements

### Requirement: 患者と依頼の属性の名前

画面の見出し・項目の名前と `docs/spec/` の表では、患者と依頼の属性に次の名前を使わなければ
ならない（SHALL）。用語の表に無い属性は、英語の属性名をそのまま使う。

| 属性 | 名前 |
|------|------|
| Accession Number (0008,0050) | 受付番号 |
| Patient ID (0010,0020) | 患者 ID |
| Patient's Name (0010,0010) | 患者氏名 |
| Patient's Birth Date (0010,0030) | 生年月日 |
| Patient's Sex (0010,0040) | 性別 |
| Requesting Service (0032,1033) | 依頼科 |
| Requesting Physician (0032,1032) | 依頼医 |
| Referring Physician's Name (0008,0090) | 紹介医 |
| Institution Name (0008,0080) | 施設名 |

#### Scenario: 予約の詳細の項目

- **WHEN** 利用者が予約の詳細を開く
- **THEN** 患者と依頼の項目の名前は「依頼科」「患者 ID」「患者氏名」で、表の名前と一致する

### Requirement: 検査の属性の名前

画面の見出し・項目の名前と `docs/spec/` の表では、検査の属性に次の名前を使わなければ
ならない（SHALL）。

| 属性 | 名前 |
|------|------|
| Modality (0008,0060) | モダリティ |
| Requested Procedure Description (0032,1060) | 検査名 |
| Requested Procedure Priority (0040,1003) | 優先度 |
| Specific Character Set (0008,0005) | 文字コード |

#### Scenario: 予約の詳細の検査の項目

- **WHEN** 利用者が予約の詳細を開く
- **THEN** 検査の項目の名前は「モダリティ」「検査名」「文字コード」で、表の名前と一致する

### Requirement: 予定の属性の名前

画面の見出し・項目の名前と `docs/spec/` の表では、Scheduled Procedure Step の属性に次の
名前を使わなければならない（SHALL）。

| 属性 | 名前 |
|------|------|
| Scheduled Performing Physician's Name (0040,0006) | 実施予定医 |
| Scheduled Station AE Title (0040,0001) | 予定の AE タイトル |
| Scheduled Station Name (0040,0010) | 予定の装置名 |
| Scheduled Procedure Step Start Date (0040,0002)・Time (0040,0003) | 予定日時 |

#### Scenario: 予約の一覧の見出し

- **WHEN** 利用者が予約の一覧を開く
- **THEN** 見出しは「予定日時」「受付番号」「患者 ID」「患者氏名」「生年月日・性別」「モダリティ」「検査名」「依頼科」「装置」「状態」で、DICOM の属性を表す見出しは表の名前（2つの属性の列は名前を「・」でつないだもの）と一致する（「装置」は装置の台帳の名前、「状態」は予約の状態で、DICOM の属性名の訳ではない）

#### Scenario: 予約の詳細の予定の項目

- **WHEN** 利用者が予約の詳細を開く
- **THEN** 予定の項目の名前は「予定日時」「予定の AE タイトル」「予定の装置名」で、表の名前と一致する

### Requirement: 依頼医と紹介医を取り違えない

Requesting Physician (0032,1032) を「紹介医」と、Referring Physician's Name (0008,0090) を
「依頼医」と呼んではならない（SHALL NOT）。2つの属性に同じ人を入れるときも、名前は分けて書く。

#### Scenario: 予約の項目の表

- **WHEN** 利用者が `docs/spec/01_orders.md` の 1 章の表を読む
- **THEN** 依頼医の行は Requesting Physician (0032,1032) だけ、紹介医の行は Referring Physician's Name (0008,0090) だけを指す
