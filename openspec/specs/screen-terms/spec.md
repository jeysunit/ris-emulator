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
| Patient ID (0010,0020) | 患者ID |
| Patient's Name (0010,0010) | 氏名 |
| Patient's Birth Date (0010,0030) | 生年月日 |
| Patient's Sex (0010,0040) | 性別 |
| Requesting Service (0032,1033) | 依頼科 |
| Requesting Physician (0032,1032) | 依頼医 |
| Referring Physician's Name (0008,0090) | 紹介医 |
| Institution Name (0008,0080) | 施設名 |

#### Scenario: 予約の詳細の項目

- **WHEN** 利用者が予約の詳細を開く
- **THEN** 患者と依頼の項目の名前は「依頼科」「患者ID」「氏名」で、表の名前と一致する

#### Scenario: 性別の値

- **WHEN** 患者の性別が M・F・O・U のどれか、空、4 つの外の値のいずれかである画面を開く
- **THEN** 画面は 男・女・その他・不明 のどれかを出し、空と 4 つの外の値は「不明」と出す。DICOM・HL7 の値（M・F・O・U）は画面に出さない

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
| Scheduled Station AE Title (0040,0001) | 予定の AEタイトル |
| Scheduled Station Name (0040,0010) | 予定の装置名 |
| Scheduled Procedure Step Start Date (0040,0002)・Time (0040,0003) | 予定日時 |

#### Scenario: 予約の一覧の見出し

- **WHEN** 利用者が予約の一覧を開く
- **THEN** 見出しは「予定日時」「受付番号」「氏名」「モダリティ」「検査名」「状態」の 6 列で、患者ID・生年月日・性別・装置・依頼科は選んだ予約の区画に表示される

#### Scenario: 予約の詳細の予定の項目

- **WHEN** 利用者が予約の詳細を開く
- **THEN** 予定の項目の名前は「予定日時」「予定の AEタイトル」「予定の装置名」で、表の名前と一致する

### Requirement: 依頼医と紹介医を取り違えない

Requesting Physician (0032,1032) を「紹介医」と、Referring Physician's Name (0008,0090) を
「依頼医」と呼んではならない（SHALL NOT）。2つの属性に同じ人を入れるときも、名前は分けて書く。

#### Scenario: 予約の項目の表

- **WHEN** 利用者が `docs/spec/01_orders.md` の 1 章の表を読む
- **THEN** 依頼医の行は Requesting Physician (0032,1032) だけ、紹介医の行は Referring Physician's Name (0008,0090) だけを指す

### Requirement: 語の使い分け

画面の言葉は、tsunagi-dicom・dicom-test-generator と同じ意味に同じ語を使わなければならない
（SHALL）。「患者ID」「ユーザーID」「要求ID」「AEタイトル」は、語の中に空白を入れない（文の
中の英字の前後の空白は、これまでどおり）。患者の氏名は「氏名」と書き、「患者氏名」「患者名」は
使わない。ページ送りは「ページ」と書き、「頁」は画面（読み上げの名前を含む）に出さない。
「既定」は使わず、いつも使う 1 件は「標準」、最初に入っている値は「初期設定」と書く。

#### Scenario: 画面に出ない言い方

- **WHEN** 利用者が予約の一覧・詳細・作成・一括作成・未照合の画面を開く
- **THEN** 見える文字と、読み上げの名前（`aria-label`・`title`・`placeholder`）に、「患者 ID」「患者氏名」「AE タイトル」「頁」「既定」「送り先」は出ない
