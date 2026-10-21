# 02. MWL の SCP

- 作成日：2026-10-21
- 最終更新日：2026-10-22

出典は [ADR-0001](../decisions/0001-mwl-scp-with-pynetdicom.md) の「出典」の節
（DICOM PS3.4 K.4・K.6・C.2.2.2）。

## 1. 対応する SOP Class

| SOP Class | UID | 役割 |
|-----------|-----|------|
| Modality Worklist Information Model - FIND | 1.2.840.10008.5.1.4.31 | SCP |
| Verification | 1.2.840.10008.1.1 | SCP |

- AE タイトルは設定の `mwl.ae_title`（既定 `RIS_EMU`）。相手の Called AE
  Title が異なれば Association を拒否する（`mwl.require_called_ae_title`）
- 相手の Calling AE Title は検証しない（開発・テスト用）

## 2. 応答の流れ

1. 要求に照合キーが1つも無ければ、一致なしで Success（PS3.4 K.4.1.3.1）
2. データベースから、設定の `mwl.statuses` の状態の予約を読み込む
3. 予約ごとに、保持する属性をすべて入れた Dataset を作成し、照合する（3 章）
4. 一致した件数が `mwl.max_results`（既定 1000）を超えたら、何も返さずに
   `A700`（Refused: Out of resources）
5. 一致した予約ごとに、要求の属性だけを含む応答を Pending で返し、
   最後に Success（`0000`）。要求にこの SCP が保持しない属性があれば
   Pending は `FF01`、無ければ `FF00`
6. 途中で C-CANCEL を受けたら、残りを返さずに Cancel（`FE00`）。照合は
   応答を返す前にまとめて済ませるので、C-CANCEL を確認するのは応答を返す間と、
   最後のステータスを返す前
7. 処理のエラーは `C001`（Unable to process）。理由はログに出力する

## 3. 照合

| 種類 | 対象の VR | 規則 |
|------|-----------|------|
| Universal | すべて | 空の値はすべてに一致する |
| Single Value | AE・CS・LO・SH など | 完全一致（大文字と小文字を区別する） |
| Wild Card | AE・CS・LO・PN・SH など | `*`（0 文字以上）・`?`（1 文字） |
| Range | DA・TM・DT | `a-b`・`-b`・`a-`。TM は `HH`・`HHMM` を `HHMMSS.ffffff` の形式に揃えて比較する（上限の欠けた桁は最大値で補う） |
| List of UID | UI | `\` で区切った値のどれかに一致 |
| Sequence | SQ | 要求の項目の条件に合う項目が1つでもあれば一致。項目が空なら条件にしない |

- 予定日と予定時刻が両方とも範囲指定なら、日時の期間として比較する
  （例：日付 `20261005-20261007`・時刻 `1000-1800` は 10/5 10:00 から
  10/7 18:00 まで。PS3.4 Table K.6-1 の Remark）
- **PN**：大文字と小文字を区別しない（PS3.4 C.2.2.2.1.1 で選択できる形）。
  要求に `=` が無ければ、予約の氏名の全体と、英字・漢字・かなの各コンポーネント
  グループのどれかに一致すれば一致とする。`=` があれば、要求の空でないコンポーネント
  グループごとに、同じ位置のコンポーネントグループと比較する
- この SCP が保持しない属性の条件は無視する（Return Key としてだけ扱う）
- Specific Character Set (0008,0005) と Timezone Offset From UTC (0008,0201) は
  照合しない（PS3.4 C.2.2.2）。要求の値は、pydicom がその文字コードで
  文字列にデコードしてから比較する

## 4. 返す属性

### 4.1 保持する属性

PS3.4 Table K.6-1 の Return Key Type 1・2 の属性と、モダリティが画像に転記するために
要求することのある属性を保持する。

| モジュール | 属性 |
|------------|------|
| Scheduled Procedure Step Sequence の中 | Scheduled Station AE Title・Scheduled Station Name・Start Date・Start Time・Modality・Scheduled Performing Physician's Name・Scheduled Procedure Step Description・Scheduled Protocol Code Sequence・Scheduled Procedure Step ID・Scheduled Procedure Step Location・Pre-Medication・Requested Contrast Agent・Scheduled Procedure Step Status |
| Requested Procedure | Requested Procedure ID・Description・Code Sequence・Study Instance UID・Referenced Study Sequence（空）・Requested Procedure Priority・Patient Transport Arrangements（空）・Reason for the Requested Procedure（空） |
| Imaging Service Request | Accession Number・Issuer of Accession Number Sequence（設定の `issuer_namespace`。ADR-0005）・Requesting Physician・Referring Physician's Name・Requesting Service・Institution Name |
| Visit | Admission ID（空）・Current Patient Location（空）・Referenced Patient Sequence（空） |
| Patient | Patient's Name・Patient ID・Issuer of Patient ID（設定の `issuer_namespace`）・Birth Date・Sex・Weight・Size・Confidentiality Constraint on Patient Data Description（空） |
| Patient Medical | Patient State・Pregnancy Status・Medical Alerts・Allergies・Special Needs（どれも空） |

Table K.6-1（2026d）の Return Key Type 2 の属性はすべて保持する。
（空）は値を持たず、要求されたら空の値で返す属性。

### 4.2 応答に含める属性

- 要求にあった属性だけを含める（PS3.4 K.4.1.1.3.2）
- 要求にあって保持しない属性は、空の値で返す
- Sequence は、要求の項目が空（項目なし、または属性なしの項目）なら、保持する
  項目をすべて返す。属性があればその属性だけを返す
- Specific Character Set には予約の値を必ず入れる

## 5. 文字コード

予約ごとに3つから選ぶ（既定は設定の `orders.default_character_set`）。

| 選択 | Specific Character Set |
|------|------------------------|
| `utf8`（既定） | `ISO_IR 192` |
| `jis` | `\ISO 2022 IR 87`（値 1 は空＝ISO 2022 IR 6） |
| `jis_kana` | `ISO 2022 IR 13\ISO 2022 IR 87` |

- 氏名は英字・漢字・カナの3つのコンポーネントグループで保持し、どの選択でも
  そのまま書く（カナは全角。JIS X 0208 で表せる）
- `jis_kana` でも半角カナは出力しない。英字のコンポーネントグループを半角カナに
  する形（PS3.5 H.3.2 の例 `ﾔﾏﾀﾞ^ﾀﾛｳ=山田^太郎=やまだ^たろう`）は生成しない
- 選んだ文字コードで表せない文字がある予約は、作成時にエラーにする（[01_orders.md](01_orders.md) の 3.3）
- 要求の文字コードと応答の文字コードは異なってよい（PS3.4 K.4.1.1.3.2）

## 6. Conformance の要点（PS3.4 K.6.1.3.2）

- Optional の照合キー：上の 4.1 の属性はすべて照合に使える
- PN の大文字と小文字を区別しない照合：Patient's Name・Scheduled Performing
  Physician's Name・Requesting Physician・Referring Physician's Name
- fuzzy semantic matching の Extended Negotiation：対応しない
- Timezone Offset From UTC：対応しない。日時はサーバーのローカル時刻（`TZ`）の値
