# ADR-0003: 発番する識別子は DICOM・HL7 v2・FHIR R5 にそのまま入る形に絞る

- 状態：採用
- 日付：2026-10-21

## 背景

この RIS は、受付番号・Requested Procedure ID・Scheduled Procedure Step ID・
Patient ID・Study Instance UID を発番し、MWL で返す。返した値は、モダリティが
画像に写して PACS へ送る。予約の情報を HL7 v2（IHE RAD-4 の OMI・ORM）や
HL7 FHIR R5 に写す試験でも、同じ値を使う。

DICOM の VR だけに合わせると、たとえば SH は `\` と制御文字以外の字を許す。
HL7 v2 の区切りの字（`^ ~ & |`）や、FHIR の URL の中でエスケープが要る字も
通ってしまい、写す先で値が変わったり割れたりする。

## 決定

1. **受付番号・Requested Procedure ID・Scheduled Procedure Step ID は、
   英数字だけで 16 字までにする。** 理由：DICOM の SH（16 字）に収まり、
   HL7 v2 と FHIR にエスケープなしで入る。IHE RAD TF-2 は OBR-18・IPC-1 の
   受付番号を 16 字までと決めているので、その長さにもそろう
2. 受付番号は `<接頭辞 英数字 4 字まで><YYYYMMDD><4 桁>` にする。
   接頭辞を 4 字にしても 16 字に収まる
3. 乱数の Patient ID は `<接頭辞 英数字 8 字まで><7 桁>`（15 字まで）にする。
   名簿の Patient ID は LO（64 字）の決まりに加え、HL7 v2 の区切りの字と
   前後の空白を断る
4. **Study Instance UID は `2.25.<UUID の 10 進>` にする**（PS3.5 B.2 の
   UUID 由来の形）。理由：登録した OID の根を持たなくても、重ならない UID を
   作れる。保存の前に PS3.5 9.1 の形（数と `.` だけ、成分は 0 で始まらない、
   64 字まで）を確かめる
5. 形を確かめる処理はモデルに置き、確かめに通らない予約は保存しない。
   試験で、各規格の長さと字の決まりに合うことを固定する

## 検討した選択肢

| 案 | 採らなかった理由 |
|----|------------------|
| DICOM の VR の決まりだけに合わせる | HL7 v2 の区切りの字や、FHIR でエスケープが要る字を含む値を発番しうる |
| 組織の OID の根の下に Study Instance UID を発番する | OID の根を登録して管理する必要がある。開発・試験用のツールでは、使う人ごとに根を用意させることになる |

## 結果

- 発番した値は、DICOM・HL7 v2・FHIR R5 のどれにも、変換せずに写せる
- 受付番号の接頭辞は 4 字まで、1 日に作れる予約は 9999 件までになる
- PID-3（CX）の ID の成分の長さは HL7 v2 の原典で確かめていない。
  名簿の Patient ID は LO の 64 字まで通す

## 出典

規格の節番号と URL は [spec/04_identifiers.md](../spec/04_identifiers.md) の
「原典」の節にまとめている。

## 関連

- [spec/01_orders.md](../spec/01_orders.md) の 2 章（番号）
- [spec/04_identifiers.md](../spec/04_identifiers.md)
- [ADR-0004](0004-ris-issues-study-instance-uid.md)
