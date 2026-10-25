# 01. 予約

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
| 装置 | （MWL には入れない） | モダリティごとに、設定の装置の台帳（`stations`）から名前で選ぶ。予約作成の画面の既定は台帳の1台目。一括作成と CLI で選ばなければ、台帳の装置を予約ごとに順に使う（画面では「全装置に振り分け」） |
| 予定の AEタイトル | Scheduled Station AE Title (0040,0001) | 選んだ装置の `ae_title` |
| 予定の装置名 | Scheduled Station Name (0040,0010) | 選んだ装置の `station_name`（空なら空の値で返す。Return Key Type 2） |
| 予定日時 | Scheduled Procedure Step Start Date・Time | 4 章 |
| 検査名 | Requested Procedure Description・Scheduled Procedure Step Description | 予約作成の画面では、モダリティの設定の検査の種類から選ぶ。一括作成と CLI では乱数で選ぶ |
| 検査コード | Requested Procedure Code Sequence・Scheduled Protocol Code Sequence | 同じ検査の種類のコード（既定の Coding Scheme Designator は `99RISEMU`） |
| 依頼科 | Requesting Service (0032,1033) | 指定。無ければ設定の `departments` から乱数で選ぶ |
| 依頼医 | Requesting Physician (0032,1032) | 乱数で生成した氏名 |
| 紹介医 | Referring Physician's Name (0008,0090) | 依頼医と同じ氏名（院内の依頼医を紹介医にも入れる） |
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
- 患者ID：`<patient_id_prefix><7 桁の乱数>`。データベースにある ID と、
  同じ作成要求で生成した ID とは重複させない
- 性別は M・F、年齢は予定日の時点で 0〜95 歳。身長と体重は年齢と性別から
  概算の値を生成する（Patient's Size は m、Patient's Weight は kg）
- CLI でシード（`--seed`）を指定すると、同じシードで同じ患者を生成する（画面には無い）

### 3.2 名簿

- 1人分の項目は `patient_id`・`patient_name.alphabetic/ideographic/phonetic`・
  `birth_date`・`sex`・`weight`（kg）・`size`（cm）。例は `data/patients_sample.yaml`
- 予約作成の画面では、名簿の患者を1人選ぶ（名簿が読めなければ選べない）
- 一括作成（「名簿から無作為に」）と CLI（`--patients roster`）では、予約ごとに名簿から
  乱数で選ぶ（同じ患者が何度選ばれてもよい）
- 名簿のファイルは設定の `orders.roster_path` で指定する
- 氏名の各コンポーネントグループは 64 文字まで。`=`・`\`・制御文字を含む名簿は
  読み込まない（PS3.5 6.2 の PN の規則）

### 3.3 文字コードで表せない文字

予約を保存する前に、PN・LO などの文字列の値をすべて、その予約の
Specific Character Set で表せるかを検証する。表せない文字があれば、属性と文字を
示して作成をエラーにする（pydicom は表せない文字を `?` に置き換えるため）。
例：`髙`・`𠮷` は JIS X 0208 に無いので、`jis`・`jis_kana` では作成できない。

### 3.4 手で入れた患者の入力の確かめ

予約作成の画面の患者は、名簿から選ぶか乱数で生成するかで、手で入れる欄は無い。患者を
手で入れるのは、照合の画面（[07](07_reconciliation.md) の 5 章）と CLI の
`reconcile run`・`pir send`。この 3 つは、同じ規則（`app/core/patient_input.py`）で
確かめ、誤りは日本語の文で断る。照合のサービス（`ReconciliationService.reconcile`）も同じ
確かめを行う。文には入れた値を出さない。

- 患者ID：64 字まで（LO）。基本の文字集合の表示できる字で、`\` と HL7 v2 の区切り
  （`^ ~ & |`）は使えない。前後の空白も断る
- 氏名：1つの成分グループは 64 字まで、成分は 5 つまで。`=`・`\`・制御文字は使えない
  （PS3.5 6.2）。画面の姓・名の欄には `^` も入れられない
  - 英字：半角の英字・空白・ハイフン・アポストロフィだけ。全角や日本語は断る
  - 漢字：JIS X 0208 で表せる字（と ASCII）。表せない字と半角カナは断る
  - かな：文字の種類は見ない（ひらがな・カタカナ・半角カナのどれを許すかは未決）。
    決まったら `check_phonetic_group` に規則を足す
- 生年月日：暦にある YYYYMMDD で、今日以前
- 性別：M・F・O か空

画面の照合のフォームは、入力のたびにスクリプトが同じ文を欄の下に出し、誤りがあるうちは
送信を止める。漢字の氏名は JIS X 0208 の近似で確かめ、最後の判定はサーバーが行う。

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
| 中止 | `discontinued` | - | 返さない |

- 取消は撮影を始める前の取り消し、中止は始めた撮影を途中で止めたこと（MPPS の
  `DISCONTINUED`。PS3.3 C.4.14 の「取り消された、または正常に終わらなかった」）
- 状態は、画面と CLI の手動の変更と、MPPS（[05_mpps_scp.md](05_mpps_scp.md)）で変わる。
  どちらも次の表のとおりにだけ変える（行が今の状態、列が変更後の状態）

| 今の状態 | 予定 | 実施中 | 完了 | 取消 | 中止 |
|----------|------|--------|------|------|------|
| 予定 | - | 可 | 可 | 可 | 不可 |
| 実施中 | 可 | - | 可 | 可 | 可 |
| 完了 | 不可 | 不可 | - | 不可 | 不可 |
| 取消 | 不可 | 不可 | 不可 | - | 不可 |
| 中止 | 不可 | 不可 | 不可 | 不可 | - |

- 完了・取消・中止は終わりの状態で、ほかの状態へ変更できない。完了・取消の予約を予定に
  戻すと MWL でもう一度返り、同じ Study Instance UID でもう一度撮影できてしまう。HL7 v2 の
  Table 0038 Order Status でも、CM（完了）・CA（取消）・DC（中止）は終わりの状態。
  やり直すときは新しい予約を作る
- 中止にできるのは実施中の予約だけ（まだ撮影を始めていない予定の予約は、取消にする）
- 実施中から予定へは戻せる（実施中への誤操作を戻すため）
- 今と同じ状態を指定したときは、何も変えずに成功にする（更新日時も変えない）
- 表に無い向きは、CLI では終了コード 2、画面では 400 で断る。状態の確認と書き込みは
  1つのトランザクションで行う（画面と CLI から同時に変更しても、表に無い向きの変更は
  保存されない）
- 画面の選択肢には、今の状態と、今の状態から変更できる状態だけを出す。終わりの状態の
  予約には選択肢を出さず、状態の名前だけを表示する
- MWL で返す状態は設定の `mwl.statuses` で指定する（終わりの状態は指定できない）
- `SCHEDULED`・`STARTED` は PS3.3 C.4.10 の Defined Terms

## 6. 一度に作成できる件数

1 回の作成要求で合計 200 件まで。モダリティは設定の `orders.modalities` にあるものだけ。

## 7. 撮り直し

撮影をやり直すときの扱いは、設定の `orders.retake_mode` で選ぶ。理由は
[ADR-0008](../decisions/0008-retake-mode.md) にある。

| 値 | 扱い | RIS がすること |
|----|------|----------------|
| `append`（既定） | 同じ予約・同じ Study Instance UID の中で、2つ目以降の MPPS とシリーズを追加する（IHE RAD TF-2 4.6.4.1.2.3.3 Append Case） | 何もしない。2つ目以降の MPPS は [05_mpps_scp.md](05_mpps_scp.md) のとおりに記録し、予約が終わりの状態なら状態を変えない |
| `new_order` | 撮り直しは別の検査で、受付番号から Study Instance UID まで変わる（施設のローカルルール） | 撮り直しの予約を作る |

`new_order` のときの撮り直しの予約：

- 予約の詳細の画面と CLI の `retake <受付番号>` で作る。`append` のときは作らない
  （CLI は終了コード 2、画面はボタンを出さない）
- 元の予約が実施中・完了・中止のときだけ作れる。予定の予約はまだ撮っていない、
  取消の予約は検査そのものを取り消したので、撮り直しを作らない（終了コード 2・400）
- 患者・モダリティ・予定の AEタイトルと装置名・検査・依頼科・依頼医・紹介医・施設名・
  優先度・文字コードを元の予約から写す
- 受付番号・Requested Procedure ID・Scheduled Procedure Step ID・Study Instance UID は、
  新しい予約と同じ規則（2 章）で発番する。状態は予定
- 予定日時は、指定が無ければ作った時点の日付と時刻（分まで）にする。モダリティは今日の
  日付で MWL を引くことが多く、ほかの日にすると撮り直しの予約が返らない
- 元の予約が実施中なら中止にする（始めた撮影が正常に終わらなかった。PS3.3 C.4.14 の
  DISCONTINUED）。完了・中止ならそのまま（終わりの状態は変えない）
- 撮り直しの予約に元の受付番号（`retake_of`）を残し、予約の詳細に「撮り直しの元」と
  「撮り直し」を互いにリンクで表示する。撮り直しの予約から、さらに撮り直しを作ってもよい。
  この関係は MWL の属性には入れない（MWL に元の予約を表す属性が無いため）
- 元の予約の確認・撮り直しの予約の保存・元の予約の状態の変更は、1つのトランザクションで
  行う。途中で失敗したら何も残さず、連番も使わない
