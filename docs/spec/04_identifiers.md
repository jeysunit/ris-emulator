# 04. 発番する識別子と規格

- 作成日：2026-10-21
- 最終更新日：2026-10-22

この RIS が発番する識別子は、DICOM の VR の決まりに合わせ、さらに HL7 v2
（IHE RAD-4 の OMI・ORM）と HL7 FHIR R5 にエスケープや変換なしでそのまま
入る形に絞る。確かめた原典は 3 章（2026-10-21 に確かめた）。
この形にした理由は [ADR-0003](../decisions/0003-identifiers-fit-dicom-and-hl7.md)・
[ADR-0004](../decisions/0004-ris-issues-study-instance-uid.md)・
[ADR-0005](../decisions/0005-return-issuer-namespace.md) にある。

## 1. 表

| 識別子 | DICOM（属性・VR・長さ） | この RIS の形 | HL7 v2（IHE RAD TF-2） | FHIR R5 |
|--------|--------------------------|---------------|-------------------------|---------|
| 受付番号 | Accession Number (0008,0050)・SH・16 字。`\` と制御文字（ESC を除く）は不可（PS3.5 6.2） | `<接頭辞 英数字 4 字まで><YYYYMMDD><4 桁>`。英数字だけで 16 字まで（例 `RE202610210001`） | OBR-18 Placer Field 1（v2.3.1、Table 4.4-6）、IPC-1 Accession Identifier（v2.5.1、4.4.4.1.2.2.8）。どちらも 16 字までと IHE が決めている | `ServiceRequest.identifier`、type は `http://terminology.hl7.org/CodeSystem/v2-0203` の `ACSN`（ImagingStudy の Notes の例）。値は string |
| Requested Procedure ID | (0040,1001)・SH・16 字 | `RP<YYYYMMDD><4 桁>`（14 字） | OBR-19 Placer Field 2（Table 4.4-6）、IPC-2（EI・22 字、Table 4.4-16） | `ServiceRequest.identifier`（type は決めない） |
| Scheduled Procedure Step ID | (0040,0009)・SH・16 字 | `SPS<YYYYMMDD><4 桁>`（15 字） | OBR-20 Filler Field 1（Table 4.4-6）、IPC-4（EI・22 字、Table 4.4-16） | 写す先は決めない |
| Patient ID | (0010,0020)・LO・64 字。`\` と制御文字は不可（PS3.5 6.2） | 乱数は `<接頭辞 英数字 8 字まで><7 桁>`（15 字まで）。名簿は LO の決まりに加え、HL7 v2 の区切りの字 `^ ~ & \|` と前後の空白を断る | PID-3（Assigning Authority の namespace ID を必ず入れる。RAD TF-2 の PID の節） | `Patient.identifier` の値 |
| Study Instance UID | (0020,000D)・UI・64 字。数と `.` だけ、成分は 0 で始まらない（PS3.5 9.1） | `2.25.<UUID の 10 進>`（PS3.5 B.2 の UUID 由来の形。UUID は 39 桁まで、全体で 44 字まで） | ZDS-1（RP・200 字、v2.3.1、Table 4.4-7）、IPC-3（EI・70 字、v2.5.1、Table 4.4-16） | `ImagingStudy.identifier`：system `urn:dicom:uid`、value `urn:oid:<UID>`。FHIR の oid 型の正規表現 `urn:oid:[0-2](\.(0\|[1-9][0-9]*))+` に合う |
| 発番の出どころ | Issuer of Patient ID (0010,0021)・LO、Issuer of Accession Number Sequence (0008,0051) の Local Namespace Entity ID | 設定の `orders.issuer_namespace`（既定 `RIS_EMU`、英数字と `_` で 16 字まで。空なら返さない） | PID-3 の Assigning Authority の namespace ID、IPC-1 の namespace ID | `Identifier.system` に写すときは、使う側が URI を決める（ADR-0005） |

## 2. 確かめること

- 受付番号・Requested Procedure ID・Scheduled Procedure Step ID は、英数字だけで
  16 字までに限る（`app/core/models.py` の `IDENTIFIER_PATTERN`）
- Study Instance UID は PS3.5 9.1 の形を確かめてから保存する（`is_valid_uid`）。
  Study Instance UID は予約を作るときに発番し、要求に含まれていれば MWL で値を返す
  （Return Key Type 1）
- 名簿の Patient ID に HL7 v2 の区切りの字があれば、名簿を読まない
- Issuer of Patient ID と Issuer of Accession Number Sequence は
  `orders.issuer_namespace` の値で返す。`issuer_namespace: ""` にすれば、
  Issuer of Patient ID は空、Issuer of Accession Number Sequence は項目なしで返す
- これらの決まりは `tests/core/test_identifiers.py` で固定している

## 3. 原典

- DICOM PS3.5 2026d 6.2 Value Representation（SH・LO・UI）
  <https://dicom.nema.org/medical/dicom/current/output/chtml/part05/sect_6.2.html>
- DICOM PS3.5 2026d 9.1 UID Encoding Rules
  <https://dicom.nema.org/medical/dicom/current/output/chtml/part05/chapter_9.html>
- DICOM PS3.5 2026d B.2 UUID Derived UID
  <https://dicom.nema.org/medical/dicom/current/output/chtml/part05/sect_B.2.html>
- DICOM PS3.3 2026d C.4.12 Imaging Service Request Module（Accession Number・
  Issuer of Accession Number Sequence）
  <https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.4.12.html>
- DICOM PS3.3 2026d C.4.11 Requested Procedure Module（Requested Procedure ID・
  Study Instance UID）、C.4.10 Scheduled Procedure Step Module、
  C.2.2 Patient Identification Module
  <https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.4.11.html>
- DICOM PS3.4 2026d Table K.6-1
  <https://dicom.nema.org/medical/dicom/current/output/chtml/part04/sect_K.6.html>
- IHE Radiology Technical Framework Volume 2 Rev. 23.0（2025-08-08）：4.4（RAD-4。
  Table 4.4-6 OBR、Table 4.4-7 ZDS、4.4.4.1.2.2.8 IPC と Table 4.4-16、
  4.4.4.1.2.2.9 Enterprise Identity Option）、4.8.4.1.1.1
  <https://www.ihe.net/uploadedFiles/Documents/Radiology/IHE_RAD_TF_Vol2.pdf>
- IHE Radiology Technical Framework Volume 1 Rev. 23.0：Figure 3.4-3
  <https://www.ihe.net/uploadedFiles/Documents/Radiology/IHE_RAD_TF_Vol1.pdf>
- HL7 FHIR R5（v5.0.0）ImagingStudy の Notes（`urn:dicom:uid`・`urn:oid:`・`ACSN`）
  <https://hl7.org/fhir/R5/imagingstudy.html>
- HL7 FHIR R5 Datatypes（oid 型の正規表現、string は 1,048,576 字まで）
  <https://hl7.org/fhir/R5/datatypes.html>

HL7 v2 の各フィールドの長さは、HL7 v2 の原典ではなく IHE RAD TF-2 の表で確かめた
（ZDS-1 は 200 字、IPC-2・IPC-4 は 22 字、IPC-3 は 70 字。OBR-18・IPC-1 は IHE が
16 字までと決めている）。発番する値はどれもこの長さに収まる。
PID-3（CX）の ID の成分の長さは HL7 v2 の原典で確かめていない。乱数の患者 ID は
15 字までにしてある（接頭辞 8 字＋7 桁）が、名簿の ID は LO の 64 字まで通す。
