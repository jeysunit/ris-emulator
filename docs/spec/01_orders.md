# 01. 予約

## 1. 予約の1件

予約の1件は、MWL の1件（Scheduled Procedure Step が1つ）に当たる。
1つの Requested Procedure に Scheduled Procedure Step は1つだけにする。

| 項目 | DICOM の属性 | 決め方 |
|------|--------------|--------|
| 受付番号 | Accession Number (0008,0050) | 2 章 |
| Requested Procedure ID | (0040,1001) | 2 章 |
| Scheduled Procedure Step ID | (0040,0009) | 2 章 |
| Study Instance UID | (0020,000D) | `2.25.` + UUID の整数 |
| 患者 | Patient's Name・ID・Birth Date・Sex・Weight・Size | 3 章 |
| モダリティ | Modality (0008,0060) | 指定 |
| 予定の AE タイトル | Scheduled Station AE Title (0040,0001) | 指定。無ければ設定のモダリティごとの値（複数あれば順に回す） |
| 予定の装置名 | Scheduled Station Name (0040,0010) | 設定のモダリティごとの値 |
| 予定の日時 | Scheduled Procedure Step Start Date・Time | 4 章 |
| 検査名 | Requested Procedure Description・Scheduled Procedure Step Description | 設定の検査の種類から乱数で選ぶ |
| 検査のコード | Requested Procedure Code Sequence・Scheduled Protocol Code Sequence | 同じ検査の種類のコード（既定の Coding Scheme Designator は `99RISEMU`） |
| 依頼科 | Requesting Service (0032,1033) | 指定。無ければ設定の `departments` から乱数で選ぶ |
| 依頼医 | Requesting Physician・Referring Physician's Name | 乱数の氏名（同じ人） |
| 施設名 | Institution Name | 設定の `institution_name` |
| 優先度 | Requested Procedure Priority | `ROUTINE` |
| 文字コード | Specific Character Set | [02_mwl_scp.md](02_mwl_scp.md) の 5 章 |
| 状態 | Scheduled Procedure Step Status | 5 章 |

## 2. 番号

- 受付番号：`<accession_prefix><作った日 YYYYMMDD><4 桁の連番>`
  （例 `RE202610210001`）。連番は作った日ごとに 1 から数える
- Requested Procedure ID：`RP<作った日><連番>`（受付番号と同じ数）
- Scheduled Procedure Step ID：`SPS<作った日><連番>`
- 長さは SH の 16 字に収める。`accession_prefix` は英数字 4 字まで。
  1 日に作れる予約は 9999 件まで
- 連番の取得と予約の保存は1つのトランザクションで行う。作るのを断ったときは
  連番を使わない（欠番を作らない。[ADR-0002](../decisions/0002-sqlite-order-store.md)）
- モダリティによっては Requested Procedure ID を画像の Study ID（SH）に写すので、
  16 字を超えない形にしている
- 番号の形と、DICOM・HL7 v2・FHIR R5 の決まりとの対応は
  [04_identifiers.md](04_identifiers.md) にある

## 3. 患者

### 3.1 乱数

- 姓（30）と名（男 15・女 15）の表から選んだ架空の氏名を、
  英字（ヘボン式、長音を書かない）・漢字・カナの3つのコンポーネントグループで持つ
  （例 `TANAKA^HIROSHI=田中^博=タナカ^ヒロシ`）
- 患者 ID：`<patient_id_prefix><7 桁の乱数>`。保存先にある ID と、
  同じ回に作った ID とは重ねない
- 性別は M・F、年齢は予定の日の時点で 0〜95 歳。身長と体重は年齢と性別から
  だいたいの値を作る（Patient's Size は m、Patient's Weight は kg）
- シード（`seed`）を与えると、同じシードで同じ患者になる

### 3.2 名簿

- 1人の項目は `patient_id`・`patient_name.alphabetic/ideographic/phonetic`・
  `birth_date`・`sex`・`weight`（kg）・`size`（cm）。例は `data/patients_sample.yaml`
- 予約ごとに名簿から乱数で選ぶ（同じ患者が何度も出てよい）
- 名簿のファイルは設定の `orders.roster_path` で指す
- 氏名の各コンポーネントグループは 64 字まで。`=`・`\`・制御文字を含む名簿は読まない
  （PS3.5 6.2 の PN の決まり）

### 3.3 文字コードで書けない字

予約を保存する前に、PN・LO などの文字の値をすべて、その予約の
Specific Character Set で書けるかを確かめる。書けない字があれば、属性と字を
示して作らない（pydicom は書けない字を黙って `?` にするため）。
例：`髙`・`𠮷` は JIS X 0208 に無いので、`jis`・`jis_kana` では作れない。

## 4. 予定の日時

- 予定の日は1つ（`today`・`tomorrow`・`YYYYMMDD`）。1900〜9999 年に限る
- 開始の時刻（既定 09:00）から、間隔（既定 15 分）ごとに並べる。
  モダリティごとに開始の時刻から数える（装置ごとの予定表）
- その日のうちに収まらなければ作らない

## 5. 状態

| 状態 | 値 | MWL の Scheduled Procedure Step Status | MWL で返すか（既定） |
|------|----|----------------------------------------|----------------------|
| 予定 | `scheduled` | `SCHEDULED` | 返す |
| 実施中 | `in_progress` | `STARTED` | 返す |
| 完了 | `completed` | - | 返さない |
| 取消 | `cancelled` | - | 返さない |

- 状態は画面と CLI で手で変える。どの状態からどの状態へも変えられる
- MWL で返す状態は設定の `mwl.statuses` で決める（完了・取消は入れられない）
- `SCHEDULED`・`STARTED` は PS3.3 C.4.10 の Defined Terms
- MPPS で状態を進めるのは次の段（[roadmap.md](../roadmap.md)）

## 6. 一度に作れる数

1 回に合わせて 200 件まで。モダリティは設定の `orders.modalities` にあるものだけ。
