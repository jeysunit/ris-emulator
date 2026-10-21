# 01. 予約

- 作成日：2026-10-21
- 最終更新日：2026-10-22

## 1. 予約の単位

予約1件は、MWL の1件（Scheduled Procedure Step が1つ）に対応する。
1つの Requested Procedure に Scheduled Procedure Step は1つだけにする。

| 項目 | DICOM の属性 | 値の決め方 |
|------|--------------|------------|
| 受付番号 | Accession Number (0008,0050) | 2 章 |
| Requested Procedure ID | (0040,1001) | 2 章 |
| Scheduled Procedure Step ID | (0040,0009) | 2 章 |
| Study Instance UID | (0020,000D) | `2.25.` + UUID の整数 |
| 患者 | Patient's Name・ID・Birth Date・Sex・Weight・Size | 3 章 |
| モダリティ | Modality (0008,0060) | 指定 |
| 予定の AE タイトル | Scheduled Station AE Title (0040,0001) | 指定。無ければ設定のモダリティごとの値（複数あれば順に使う） |
| 予定の装置名 | Scheduled Station Name (0040,0010) | 設定のモダリティごとの値 |
| 予定日時 | Scheduled Procedure Step Start Date・Time | 4 章 |
| 検査名 | Requested Procedure Description・Scheduled Procedure Step Description | 設定の検査の種類から乱数で選ぶ |
| 検査コード | Requested Procedure Code Sequence・Scheduled Protocol Code Sequence | 同じ検査の種類のコード（既定の Coding Scheme Designator は `99RISEMU`） |
| 依頼科 | Requesting Service (0032,1033) | 指定。無ければ設定の `departments` から乱数で選ぶ |
| 依頼医 | Requesting Physician・Referring Physician's Name | 乱数で生成した氏名（同一人物） |
| 施設名 | Institution Name | 設定の `institution_name` |
| 優先度 | Requested Procedure Priority | `ROUTINE` |
| 文字コード | Specific Character Set | [02_mwl_scp.md](02_mwl_scp.md) の 5 章 |
| 状態 | Scheduled Procedure Step Status | 5 章 |

## 2. 採番

- 受付番号：`<accession_prefix><作成日 YYYYMMDD><4 桁の連番>`
  （例 `RE202610210001`）。連番は作成日ごとに 1 から数える
- Requested Procedure ID：`RP<作成日><連番>`（受付番号と同じ連番）
- Scheduled Procedure Step ID：`SPS<作成日><連番>`
- 長さは SH の 16 文字に収める。`accession_prefix` は英数字 4 文字まで。
  1 日に作成できる予約は 9999 件まで
- 連番の取得と予約の保存は1つのトランザクションで行う。作成をエラーにしたときは
  連番を消費しない（欠番を作らない。[ADR-0002](../decisions/0002-sqlite-order-store.md)）
- モダリティによっては Requested Procedure ID を画像の Study ID（SH）に転記するので、
  16 文字を超えない形式にしている
- 番号の形式と、DICOM・HL7 v2・FHIR R5 の規則との対応は
  [04_identifiers.md](04_identifiers.md) にある

## 3. 患者

### 3.1 乱数による生成

- 姓（30）と名（男 15・女 15）の表から選んだ架空の氏名を、
  英字（ヘボン式、長音を表記しない）・漢字・カナの3つのコンポーネントグループで保持する
  （例 `TANAKA^HIROSHI=田中^博=タナカ^ヒロシ`）
- 患者 ID：`<patient_id_prefix><7 桁の乱数>`。データベースにある ID と、
  同じ作成要求で生成した ID とは重複させない
- 性別は M・F、年齢は予定日の時点で 0〜95 歳。身長と体重は年齢と性別から
  概算の値を生成する（Patient's Size は m、Patient's Weight は kg）
- シード（`seed`）を指定すると、同じシードで同じ患者を生成する

### 3.2 名簿

- 1人分の項目は `patient_id`・`patient_name.alphabetic/ideographic/phonetic`・
  `birth_date`・`sex`・`weight`（kg）・`size`（cm）。例は `data/patients_sample.yaml`
- 予約ごとに名簿から乱数で選ぶ（同じ患者が何度選ばれてもよい）
- 名簿のファイルは設定の `orders.roster_path` で指定する
- 氏名の各コンポーネントグループは 64 文字まで。`=`・`\`・制御文字を含む名簿は
  読み込まない（PS3.5 6.2 の PN の規則）

### 3.3 文字コードで表せない文字

予約を保存する前に、PN・LO などの文字列の値をすべて、その予約の
Specific Character Set で表せるかを検証する。表せない文字があれば、属性と文字を
示して作成をエラーにする（pydicom は表せない文字を `?` に置き換えるため）。
例：`髙`・`𠮷` は JIS X 0208 に無いので、`jis`・`jis_kana` では作成できない。

## 4. 予定日時

- 予定日は1日だけ指定する（`today`・`tomorrow`・`YYYYMMDD`）。1900〜9999 年に限る
- 開始時刻（既定 09:00）から、間隔（既定 15 分）ごとに並べる。
  モダリティごとに開始時刻から数える（装置ごとの予定表）
- その日のうちに収まらなければ作成しない

## 5. 状態

| 状態 | 値 | MWL の Scheduled Procedure Step Status | MWL で返すか（既定） |
|------|----|----------------------------------------|----------------------|
| 予定 | `scheduled` | `SCHEDULED` | 返す |
| 実施中 | `in_progress` | `STARTED` | 返す |
| 完了 | `completed` | - | 返さない |
| 取消 | `cancelled` | - | 返さない |

- 状態は画面と CLI で手動で変更する。どの状態からどの状態へも変更できる
- MWL で返す状態は設定の `mwl.statuses` で指定する（完了・取消は指定できない）
- `SCHEDULED`・`STARTED` は PS3.3 C.4.10 の Defined Terms
- MPPS で状態を進める機能は、次に作るもの（[roadmap.md](../roadmap.md)）

## 6. 一度に作成できる件数

1 回の作成要求で合計 200 件まで。モダリティは設定の `orders.modalities` にあるものだけ。
