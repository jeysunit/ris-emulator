# ADR-0004: Study Instance UID は予約を作るときに RIS が発番する

- 状態：採用
- 日付：2026-10-21
- 作成日：2026-10-22

## 背景

Study Instance UID (0020,000D) を、予約を作る RIS が発番するか、撮影する
モダリティが発番するかを決める必要があった。MWL で返さなければ、モダリティが
撮影のときに作ることになる。

規格の決まりは次のとおり。

- DICOM PS3.4 Table K.6-1：Study Instance UID は Requested Procedure の属性で、
  Matching Key Type O・Return Key Type 1（要求に含まれていれば、SCP は必ず値を返す）
- IHE RAD TF-2 4.8.4.1.1.1（Study UIDs and Series UIDs）：Scheduled Workflow では
  Order Filler が生成し、Modality Worklist でモダリティに渡す。モダリティが作るのは、
  予約の無い撮影（RAD TF-2x Appendix A の Table A.1-2）などの例外だけ
- IHE RAD TF-2 4.4（Procedure Scheduled [RAD-4]）：Order Filler（DSS/OF）は
  Study Instance UID を ZDS-1（v2.3.1）・IPC-3（v2.5.1）で Image Manager に送る
- IHE RAD TF-1 Figure 3.4-3（Scheduled Workflow の情報モデル）：Requested Procedure は
  識別子として Accession Number・Study Instance UID・Requested Procedure ID を持つ

## 決定

1. **この RIS は Order Filler（DSS/OF）の役を務めるので、Study Instance UID を
   予約を作るときに発番し、要求に含まれていれば MWL で値を返す。** 理由：
   Return Key Type 1 なので、要求されたときに値が無いと規格に合わない。
   IHE の Scheduled Workflow でも Order Filler が作る
2. UID の形は [ADR-0003](0003-identifiers-fit-dicom-and-hl7.md) に従う

## 検討した選択肢

| 案 | 採らなかった理由 |
|----|------------------|
| MWL で返さず、モダリティに作らせる | Return Key Type 1 の属性を返さないことになる。IHE の Scheduled Workflow では、モダリティが作るのは予約の無い撮影などの例外に限られる |

## 結果

- モダリティは MWL で受けた Study Instance UID を画像に写せばよい
- 予約の情報を HL7 v2 で写す試験でも、ZDS-1・IPC-3 に同じ UID を入れられる

## 出典

規格の節番号と URL は [spec/04_identifiers.md](../spec/04_identifiers.md) の
「原典」の節にまとめている。

## 関連

- [ADR-0003](0003-identifiers-fit-dicom-and-hl7.md)
- [spec/04_identifiers.md](../spec/04_identifiers.md)
