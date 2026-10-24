# 05. MPPS の SCP

モダリティから MPPS（Modality Performed Procedure Step）の N-CREATE・N-SET を受け、
撮影の開始・完了・中止を予約の状態に反映する。設計の理由は
[ADR-0007](../decisions/0007-mpps-advances-order-status.md) にある。
出典は DICOM PS3.4 F.7.2、PS3.3 C.4.14、PS3.7 C.5・10.1.5（2026d）。

## 1. 対応する SOP Class

| SOP Class | UID | 役割 |
|-----------|-----|------|
| Modality Performed Procedure Step | 1.2.840.10008.3.1.2.3.3 | SCP（N-CREATE・N-SET） |

- MWL の SCP と同じ AE タイトル・ポートで受ける。Called AE Title の検証も MWL と
  同じ設定（`mwl.ae_title`・`mwl.require_called_ae_title`）を使う
- N-GET（Modality Performed Procedure Step Retrieve）と N-EVENT-REPORT
  （Modality Performed Procedure Step Notification）には対応しない

## 2. N-CREATE

1. 要求に Affected SOP Instance UID が無ければ、SCP が `2.25.` と UUID の整数で発番し、
   応答の Affected SOP Instance UID で返す（PS3.7 10.1.5.1.4）。あれば PS3.5 9.1 の
   UID の形かを確かめ、違えば `0106`（Invalid Attribute Value）
2. Performed Procedure Step Status (0040,0252) が無ければ `0120`（Missing Attribute）、
   `IN PROGRESS` でなければ `0106`（PS3.4 F.7.2.1.3）
3. Scheduled Step Attributes Sequence (0040,0270) が無ければ `0120`
4. 同じ SOP Instance UID の MPPS がすでにあれば `0111`（Duplicate SOP Instance）
5. Scheduled Step Attributes Sequence の項目ごとに、Accession Number (0008,0050) と
   Scheduled Procedure Step ID (0040,0009) の両方が一致する予約を MPPS に結び付ける。
   1つの MPPS に複数の予約が結び付いてよい（IHE の Group Case）。一致する予約が
   無い項目は、予定の無い撮影として MPPS だけを記録する（後から正式な患者と予約を結ぶ
   操作は [07_reconciliation.md](07_reconciliation.md)）
6. 結び付いた予約を実施中にし、MPPS を記録して `0000`（Success）

断った N-CREATE は記録せず、予約も変えない。

## 3. N-SET

1. 対象の SOP Instance UID の MPPS が無ければ `0112`（No such SOP Instance）
2. 記録した Performed Procedure Step Status が `IN PROGRESS` でなければ、`0110`
   （Processing Failure）と Error ID `A710`、Error Comment
   「Performed Procedure Step Object may no longer be updated」
   （PS3.4 F.7.2.2.3、Table F.7.2-2）
3. Modification List の Performed Procedure Step Status が Enumerated Values
   （`IN PROGRESS`・`COMPLETED`・`DISCONTINUED`。PS3.3 C.4.14）に無ければ `0106`
4. `COMPLETED` なら結び付いた予約を完了に、`DISCONTINUED` なら中止にする。状態を
   含まない N-SET は、受けた属性を記録するだけ
5. 受けた属性を MPPS の記録に足して `0000`

## 4. 予約の状態と記録

- 予約の状態は [01_orders.md](01_orders.md) の 5 章の遷移の表に従って変える。結び付いた
  予約が終わりの状態（完了・取消・中止）か、MPPS が求める向きが表に無いときは、予約を
  変えずに MPPS の処理を成功にし、変えなかった予約をログに出す。PS3.4 F.7.2.1.3 は、
  予約の状態を理由に SCP が N-CREATE を断ることを定めていない
- MPPS の記録と予約の状態の変更は、1つのトランザクションで行う（片方だけが残らない）
- 記録するのは SOP Instance UID・Performed Procedure Step Status・結び付いた受付番号・
  受けた属性（pydicom の JSON の形）・受けた日時・更新日時。データベースの `mpps` の表に置く
- 予約の詳細の画面に、結び付いた MPPS の SOP Instance UID・状態・受けた日時・
  更新日時を表示する
- 想定外のエラーは `0110` にしてログに出す。SCP は止めない

## 5. 扱わないこと

- Performed Series Sequence の画像の一覧と、PACS にある画像との照合はしない
- N-SET で、Table F.7.2-1 で N-SET が Not allowed の属性（Scheduled Step Attributes
  Sequence など）が送られても、断らずに記録だけする。予約との結び付きは N-CREATE の
  値から変えない
