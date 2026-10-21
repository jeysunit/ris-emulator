# ADR-0003: 発番する識別子は DICOM・HL7 v2・FHIR R5 にそのまま入る形式に限定する

- 状態：採用
- 作成日：2026-10-22
- 最終更新日：2026-10-22

## 背景

この RIS は、受付番号・Requested Procedure ID・Scheduled Procedure Step ID・
Patient ID・Study Instance UID を発番し、MWL で返す。返した値は、モダリティが
画像に転記して PACS へ送信する。予約の情報を HL7 v2（IHE RAD-4 の OMI・ORM）や
HL7 FHIR R5 に変換するテストでも、同じ値を使う。

DICOM の VR だけに合わせると、たとえば SH は `\` と制御文字以外の文字を許す。
HL7 v2 の区切り文字（`^ ~ & |`）や、FHIR の URL の中でエスケープが必要な文字も
受け付けてしまい、変換先で値が変わったり分割されたりする。

## 決定

1. **受付番号・Requested Procedure ID・Scheduled Procedure Step ID は、
   英数字だけで 16 文字までにする。** 理由：DICOM の SH（16 文字）に収まり、
   HL7 v2 と FHIR にエスケープなしで入る。IHE RAD TF-2 は OBR-18・IPC-1 の
   受付番号を 16 文字までと規定しているので、その長さにも合う
2. 受付番号は `<接頭辞 英数字 4 文字まで><YYYYMMDD><4 桁>` にする。
   接頭辞を 4 文字にしても 16 文字に収まる
3. 乱数で生成する Patient ID は `<接頭辞 英数字 8 文字まで><7 桁>`（15 文字まで）にする。
   名簿の Patient ID は LO（64 文字）の規則に加え、HL7 v2 の区切り文字と
   前後の空白を拒否する
4. **Study Instance UID は `2.25.<UUID の 10 進表記>` にする**（PS3.5 B.2 の
   UUID 由来の形式）。理由：登録した OID のルートを持たなくても、重複しない UID を
   生成できる。保存の前に PS3.5 9.1 の形式（数字と `.` だけ、各コンポーネントは
   0 で始まらない、64 文字まで）を検証する
5. 形式の検証はモデルに置き、検証でエラーになった予約は保存しない。
   テストで、各規格の長さと文字の規則に合うことを固定する

## 検討した選択肢

| 案 | 採らなかった理由 |
|----|------------------|
| DICOM の VR の規則だけに合わせる | HL7 v2 の区切り文字や、FHIR でエスケープが必要な文字を含む値を発番しうる |
| 組織の OID のルートの下に Study Instance UID を発番する | OID のルートを登録して管理する必要がある。開発・テスト用のツールでは、利用者ごとにルートを用意させることになる |

## 結果

- 発番した値は、DICOM・HL7 v2・FHIR R5 のどれにも、変換せずに転記できる
- 受付番号の接頭辞は 4 文字まで、1 日に作成できる予約は 9999 件までになる
- PID-3（CX）の ID コンポーネントの長さは、HL7 v2 の原典では確認していない。
  名簿の Patient ID は LO の 64 文字まで受け付ける

## 出典

規格の節番号と URL は [spec/04_identifiers.md](../spec/04_identifiers.md) の
「原典」の節にまとめている。

## 関連

- [spec/01_orders.md](../spec/01_orders.md) の 2 章（採番）
- [spec/04_identifiers.md](../spec/04_identifiers.md)
- [ADR-0004](0004-ris-issues-study-instance-uid.md)
