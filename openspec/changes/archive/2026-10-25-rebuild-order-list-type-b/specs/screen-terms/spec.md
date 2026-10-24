# screen-terms 仕様の差分

## MODIFIED Requirements

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
